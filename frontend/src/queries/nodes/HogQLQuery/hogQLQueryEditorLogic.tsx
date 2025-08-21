import type { Monaco } from '@monaco-editor/react'
import { actions, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { combineUrl } from 'kea-router'
// Note: we can only import types and not values from monaco-editor, because otherwise some Monaco code breaks
// auto reload in development. Specifically, on this line:
// `export const suggestWidgetStatusbarMenu = new MenuId('suggestWidgetStatusBar')`
// `new MenuId('suggestWidgetStatusBar')` causes the app to crash, because it cannot be called twice in the same
// JS context, and that's exactly what happens on auto-reload when the new script chunks are loaded. Unfortunately
// esbuild doesn't support manual chunks as of 2023, so we can't just put Monaco in its own chunk, which would prevent
// re-importing. As for @monaco-editor/react, it does some lazy loading and doesn't have this problem.
import type { editor } from 'monaco-editor'

import { LemonDialog, LemonInput } from '@posthog/lemon-ui'

import api from 'lib/api'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { dataWarehouseSceneLogic } from 'scenes/data-warehouse/settings/dataWarehouseSceneLogic'

import { DataNode, HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

import type { hogQLQueryEditorLogicType } from './hogQLQueryEditorLogicType'

export interface HogQLQueryEditorLogicProps {
    key: string | number
    query: HogQLQuery
    setQuery?: (query: HogQLQuery) => void
    onChange?: (query: string) => void
    monaco?: Monaco | null
    editor?: editor.IStandaloneCodeEditor | null
    metadataSource?: DataNode
    queryResponse?: Record<string, any>
}

export const hogQLQueryEditorLogic = kea<hogQLQueryEditorLogicType>([
    path(['queries', 'nodes', 'HogQLQuery', 'hogQLQueryEditorLogic']),
    props({} as HogQLQueryEditorLogicProps),
    key((props) => props.key),
    propsChanged(({ actions, props }, oldProps) => {
        const selection = props.editor?.getSelection()
        const model = props.editor?.getModel()
        const highlightedQuery = selection && model ? model.getValueInRange(selection) : null

        if (highlightedQuery && props.query.query === highlightedQuery) {
            return
        }

        if (
            typeof props.query.query === 'string' &&
            (props.query.query !== oldProps.query.query || props.editor !== oldProps.editor)
        ) {
            actions.setQueryInput(props.query.query)
        }
    }),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
        actions: [dataWarehouseViewsLogic, ['createDataWarehouseSavedQuery'], dataWarehouseSceneLogic, ['updateView']],
    })),
    actions({
        saveQuery: (queryOverride?: string) => ({ queryOverride }),
        setQueryInput: (queryInput: string) => ({ queryInput }),
        setPrompt: (prompt: string) => ({ prompt }),
        setPromptError: (error: string | null) => ({ error }),
        draftFromPrompt: true,
        draftFromPromptComplete: true,
        saveAsView: true,
        saveAsViewSuccess: (name: string) => ({ name }),
        onUpdateView: true,
    }),
    reducers(({ props }) => ({
        queryInput: [
            typeof props.query.query === 'string' ? props.query.query : '',
            { setQueryInput: (_, { queryInput }) => queryInput },
        ],
        prompt: ['', { setPrompt: (_, { prompt }) => prompt }],
        promptError: [
            null as string | null,
            { setPromptError: (_, { error }) => error, draftFromPrompt: () => null, saveQuery: () => null },
        ],
        promptLoading: [false, { draftFromPrompt: () => true, draftFromPromptComplete: () => false }],
    })),
    selectors({
        aiAvailable: [() => [preflightLogic.selectors.preflight], (preflight) => preflight?.openai_available],
    }),
    listeners(({ actions, props, values }) => ({
        saveQuery: ({ queryOverride }) => {
            const query = values.queryInput
            // TODO: Is below line necessary if the only way for queryInput to change is already through setQueryInput?
            actions.setQueryInput(query)

            props.setQuery?.({
                ...props.query,
                query: queryOverride ?? query,
                variables: Object.fromEntries(
                    Object.entries(props.query.variables ?? {}).filter(([_, variable]) =>
                        query.includes(`{variables.${variable.code_name}}`)
                    )
                ),
            })
        },
        setQueryInput: async ({ queryInput }) => {
            props.onChange?.(queryInput)
        },
        draftFromPrompt: async () => {
            if (!values.aiAvailable) {
                throw new Error(
                    'To use AI features, configure environment variable OPENAI_API_KEY for this instance of PostHog'
                )
            }
            try {
                const result = await api.get(
                    combineUrl(`api/projects/@current/query/draft_sql/`, {
                        prompt: values.prompt,
                        current_query: values.queryInput,
                    }).url
                )
                const { sql } = result
                actions.setQueryInput(sql)
            } catch (e) {
                actions.setPromptError((e as { code: string; detail: string }).detail)
            } finally {
                actions.draftFromPromptComplete()
            }
        },
        saveAsView: async () => {
            LemonDialog.openForm({
                title: 'Save as view',
                initialValues: { viewName: '' },
                content: (
                    <LemonField name="viewName">
                        <LemonInput placeholder="Please enter the name of the view" autoFocus />
                    </LemonField>
                ),
                errors: {
                    viewName: (name) => (!name ? 'You must enter a name' : undefined),
                },
                onSubmit: ({ viewName }) => actions.saveAsViewSuccess(viewName),
            })
        },
        saveAsViewSuccess: async ({ name }) => {
            const query: HogQLQuery = {
                kind: NodeKind.HogQLQuery,
                query: values.queryInput,
            }
            const types = props.queryResponse?.types ?? []

            await dataWarehouseViewsLogic.asyncActions.createDataWarehouseSavedQuery({ name, query, types })
        },
        onUpdateView: async () => {
            const types = props.queryResponse?.types ?? []
            actions.updateView(values.queryInput, types)
        },
    })),
])
