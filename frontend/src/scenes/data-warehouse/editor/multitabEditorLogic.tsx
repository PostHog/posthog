import { Monaco } from '@monaco-editor/react'
import { actions, beforeUnmount, connect, kea, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import isEqual from 'lodash.isequal'
import { Uri, editor } from 'monaco-editor'
import posthog from 'posthog-js'

import { LemonDialog, LemonInput, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { initModel } from 'lib/monaco/CodeEditor'
import { codeEditorLogic } from 'lib/monaco/codeEditorLogic'
import { removeUndefinedAndNull } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightsApi } from 'scenes/insights/utils/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { queryExportContext } from '~/queries/query'
import {
    DataVisualizationNode,
    DatabaseSchemaViewTable,
    FileSystemIconType,
    HogQLMetadataResponse,
    HogQLQuery,
    NodeKind,
} from '~/queries/schema/schema-general'
import {
    Breadcrumb,
    ChartDisplayType,
    DataWarehouseSavedQuery,
    DataWarehouseSavedQueryDraft,
    ExportContext,
    LineageGraph,
    QueryBasedInsightModel,
} from '~/types'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { ViewEmptyState } from './ViewLoadingState'
import { draftsLogic } from './draftsLogic'
import { editorSceneLogic } from './editorSceneLogic'
import { fixSQLErrorsLogic } from './fixSQLErrorsLogic'
import type { multitabEditorLogicType } from './multitabEditorLogicType'
import { OutputTab, outputPaneLogic } from './outputPaneLogic'
import {
    aiSuggestionOnAccept,
    aiSuggestionOnAcceptText,
    aiSuggestionOnReject,
    aiSuggestionOnRejectText,
} from './suggestions/aiSuggestion'

export interface MultitabEditorLogicProps {
    tabId: string
    monaco?: Monaco | null
    editor?: editor.IStandaloneCodeEditor | null
}

export const NEW_QUERY = 'Untitled'

export interface QueryTab {
    uri: Uri
    view?: DataWarehouseSavedQuery
    name: string
    sourceQuery?: DataVisualizationNode
    insight?: QueryBasedInsightModel
    response?: Record<string, any>
    draft?: DataWarehouseSavedQueryDraft
}

export interface SuggestionPayload {
    suggestedValue?: string
    originalValue?: string
    acceptText?: string
    rejectText?: string
    diffShowRunButton?: boolean
    source?: 'max_ai' | 'hogql_fixer'
    onAccept: (
        shouldRunQuery: boolean,
        actions: multitabEditorLogicType['actions'],
        values: multitabEditorLogicType['values'],
        props: multitabEditorLogicType['props']
    ) => void
    onReject: (
        actions: multitabEditorLogicType['actions'],
        values: multitabEditorLogicType['values'],
        props: multitabEditorLogicType['props']
    ) => void
}

export type UpdateViewPayload = Partial<DatabaseSchemaViewTable> & {
    edited_history_id?: string
    id: string
    lifecycle?: string
    shouldRematerialize?: boolean
    sync_frequency?: string
    types: string[][]
}

function getTabHash(values: multitabEditorLogicType['values']): Record<string, any> {
    const hash: Record<string, any> = {
        q: values.queryInput ?? '',
    }
    if (values.activeTab?.view) {
        hash['view'] = values.activeTab.view.id
    }
    if (values.activeTab?.insight) {
        hash['insight'] = values.activeTab.insight.short_id
    }
    if (values.activeTab?.draft) {
        hash['draft'] = values.activeTab.draft.id
    }

    return hash
}

export const multitabEditorLogic = kea<multitabEditorLogicType>([
    path(['data-warehouse', 'editor', 'multitabEditorLogic']),
    props({} as MultitabEditorLogicProps),
    tabAwareScene(),
    connect(() => ({
        values: [
            dataWarehouseViewsLogic,
            ['dataWarehouseSavedQueries', 'dataWarehouseSavedQueryMapById'],
            userLogic,
            ['user'],
            draftsLogic,
            ['drafts'],
        ],
        actions: [
            dataWarehouseViewsLogic,
            [
                'loadDataWarehouseSavedQueriesSuccess',
                'deleteDataWarehouseSavedQuerySuccess',
                'createDataWarehouseSavedQuerySuccess',
                'runDataWarehouseSavedQuery',
                'resetDataModelingJobs',
                'loadDataModelingJobs',
                'updateDataWarehouseSavedQuerySuccess',
                'updateDataWarehouseSavedQueryFailure',
                'updateDataWarehouseSavedQuery',
            ],
            outputPaneLogic,
            ['setActiveTab'],
            editorSceneLogic,
            ['reportAIQueryPrompted', 'reportAIQueryAccepted', 'reportAIQueryRejected', 'reportAIQueryPromptOpen'],
            fixSQLErrorsLogic,
            ['fixErrors', 'fixErrorsSuccess', 'fixErrorsFailure'],
            draftsLogic,
            ['saveAsDraft', 'deleteDraft', 'saveAsDraftSuccess', 'deleteDraftSuccess'],
        ],
    })),
    actions(() => ({
        setQueryInput: (queryInput: string | null) => ({ queryInput }),
        runQuery: (queryOverride?: string, switchTab?: boolean) => ({
            queryOverride,
            switchTab,
        }),
        setActiveQuery: (query: string) => ({ query }),

        setTabs: (tabs: QueryTab[]) => ({ tabs }),
        createTab: (
            query?: string,
            view?: DataWarehouseSavedQuery,
            insight?: QueryBasedInsightModel,
            draft?: DataWarehouseSavedQueryDraft
        ) => ({
            query,
            view,
            insight,
            draft,
        }),
        updateTab: (tab: QueryTab) => ({ tab }),

        initialize: true,
        loadUpstream: (modelId: string) => ({ modelId }),
        saveAsView: (materializeAfterSave = false, fromDraft?: string) => ({ fromDraft, materializeAfterSave }),
        saveAsViewSubmit: (name: string, materializeAfterSave = false, fromDraft?: string) => ({
            fromDraft,
            name,
            materializeAfterSave,
        }),
        saveAsInsight: true,
        saveAsInsightSubmit: (name: string) => ({ name }),
        updateInsight: true,
        setFinishedLoading: (loading: boolean) => ({ loading }),
        setError: (error: string | null) => ({ error }),
        setDataError: (error: string | null) => ({ error }),
        setSourceQuery: (sourceQuery: DataVisualizationNode) => ({ sourceQuery }),
        setMetadata: (metadata: HogQLMetadataResponse | null) => ({ metadata }),
        setMetadataLoading: (loading: boolean) => ({ loading }),
        editView: (query: string, view: DataWarehouseSavedQuery) => ({ query, view }),
        editInsight: (query: string, insight: QueryBasedInsightModel) => ({ query, insight }),
        setLastRunQuery: (lastRunQuery: DataVisualizationNode | null) => ({ lastRunQuery }),
        _setSuggestionPayload: (payload: SuggestionPayload | null) => ({ payload }),
        setSuggestedQueryInput: (suggestedQueryInput: string, source?: SuggestionPayload['source']) => ({
            suggestedQueryInput,
            source,
        }),
        onAcceptSuggestedQueryInput: (shouldRunQuery?: boolean) => ({ shouldRunQuery }),
        onRejectSuggestedQueryInput: true,
        shareTab: true,
        openHistoryModal: true,
        closeHistoryModal: true,
        setInProgressViewEdit: (viewId: string, historyId: string) => ({ viewId, historyId }),
        setInProgressViewEdits: (inProgressViewEdits: Record<DataWarehouseSavedQuery['id'], string>) => ({
            inProgressViewEdits,
        }),
        deleteInProgressViewEdit: (viewId: string) => ({ viewId }),
        setInProgressDraftEdit: (draftId: string, historyId: string) => ({ draftId, historyId }),
        setInProgressDraftEdits: (inProgressDraftEdits: Record<DataWarehouseSavedQueryDraft['id'], string>) => ({
            inProgressDraftEdits,
        }),
        deleteInProgressDraftEdit: (draftId: string) => ({ draftId }),
        updateView: (view: UpdateViewPayload, draftId?: string) => ({ view, draftId }),
        updateViewSuccess: (view: UpdateViewPayload, draftId?: string) => ({ view, draftId }),
        setUpstreamViewMode: (mode: 'graph' | 'table') => ({ mode }),
        setHoveredNode: (nodeId: string | null) => ({ nodeId }),
        setTabDraftId: (tabUri: string, draftId: string) => ({ tabUri, draftId }),
        saveDraft: (activeTab: QueryTab, queryInput: string, viewId: string) => ({
            activeTab,
            queryInput,
            viewId,
        }),
    })),
    propsChanged(({ actions, props }, oldProps) => {
        if (!oldProps.monaco && !oldProps.editor && props.monaco && props.editor) {
            actions.initialize()
        }
    }),
    loaders(() => ({
        upstream: [
            null as LineageGraph | null,
            {
                loadUpstream: async (payload: { modelId: string }) => {
                    return await api.upstream.get(payload.modelId)
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        finishedLoading: [
            true,
            {
                setFinishedLoading: (_, { loading }) => loading,
            },
        ],
        sourceQuery: [
            {
                kind: NodeKind.DataVisualizationNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: '',
                },
                display: ChartDisplayType.ActionsLineGraph,
            } as DataVisualizationNode,
            {
                setSourceQuery: (_, { sourceQuery }) => sourceQuery,
            },
        ],
        lastRunQuery: [
            null as DataVisualizationNode | null,
            {
                setLastRunQuery: (_, { lastRunQuery }) => lastRunQuery,
            },
        ],
        queryInput: [
            null as string | null,
            {
                setQueryInput: (_, { queryInput }) => queryInput,
            },
        ],
        activeQuery: [
            null as string | null,
            {
                setActiveQuery: (_, { query }) => query,
            },
        ],
        editingInsight: [
            null as QueryBasedInsightModel | null,
            {
                updateTab: (_, { tab }) => tab.insight ?? null,
            },
        ],
        allTabs: [
            [] as QueryTab[],
            {
                updateTab: (_, { tab }) => [tab],
                setTabs: (_, { tabs }) => tabs,
            },
        ],
        error: [
            null as string | null,
            {
                setError: (_, { error }) => error,
            },
        ],
        metadataLoading: [
            true,
            {
                setMetadataLoading: (_, { loading }) => loading,
            },
        ],
        metadata: [
            null as HogQLMetadataResponse | null,
            {
                setMetadata: (_, { metadata }) => metadata,
            },
        ],
        editorKey: [`hogql-editor-${props.tabId}`, {}],
        suggestionPayload: [
            null as SuggestionPayload | null,
            {
                _setSuggestionPayload: (_, { payload }) => payload,
            },
        ],
        isHistoryModalOpen: [
            false as boolean,
            {
                openHistoryModal: () => true,
                closeHistoryModal: () => false,
            },
        ],
        // if a view edit starts, store the historyId in the state
        inProgressViewEdits: [
            {} as Record<DataWarehouseSavedQuery['id'], string>,
            {
                setInProgressViewEdit: (state, { viewId, historyId }) => ({
                    ...state,
                    [viewId]: historyId,
                }),
                deleteInProgressViewEdit: (state, { viewId }) => {
                    const newInProgressViewEdits = { ...state }
                    delete newInProgressViewEdits[viewId]
                    return newInProgressViewEdits
                },
                setInProgressViewEdits: (_, { inProgressViewEdits }) => inProgressViewEdits,
            },
        ],
        inProgressDraftEdits: [
            {} as Record<DataWarehouseSavedQueryDraft['id'], string>,
            {
                setInProgressDraftEdit: (state, { draftId, historyId }) => ({
                    ...state,
                    [draftId]: historyId,
                }),
                deleteInProgressDraftEdit: (state, { draftId }) => {
                    const newInProgressDraftEdits = { ...state }
                    delete newInProgressDraftEdits[draftId]
                    return newInProgressDraftEdits
                },
                setInProgressDraftEdits: (_, { inProgressDraftEdits }) => inProgressDraftEdits,
            },
        ],
        fixErrorsError: [
            null as string | null,
            {
                setQueryInput: () => null,
                fixErrorsFailure: (_, { error }) => error,
            },
        ],
        upstreamViewMode: [
            'graph' as 'graph' | 'table',
            {
                setUpstreamViewMode: (_: 'graph' | 'table', { mode }: { mode: 'graph' | 'table' }) => mode,
            },
        ],
        hoveredNode: [
            null as string | null,
            {
                setHoveredNode: (_, { nodeId }) => nodeId,
            },
        ],
    })),
    listeners(({ values, props, actions, asyncActions, cache }) => ({
        fixErrorsSuccess: ({ response }) => {
            actions.setSuggestedQueryInput(response.query, 'hogql_fixer')

            posthog.capture('ai-error-fixer-success', { trace_id: response.trace_id })
        },
        fixErrorsFailure: () => {
            posthog.capture('ai-error-fixer-failure')
        },
        shareTab: () => {
            const currentTab = values.activeTab
            if (!currentTab) {
                return
            }

            if (currentTab.insight) {
                const currentUrl = new URL(window.location.href)
                const shareUrl = new URL(currentUrl.origin + currentUrl.pathname)
                shareUrl.searchParams.set('open_insight', currentTab.insight.short_id)

                if (currentTab.insight.query?.kind === NodeKind.DataVisualizationNode) {
                    const query = (currentTab.insight.query as DataVisualizationNode).source.query
                    if (values.queryInput !== query) {
                        shareUrl.searchParams.set('open_query', values.queryInput ?? '')
                    }
                }

                void copyToClipboard(shareUrl.toString(), 'share link')
            } else if (currentTab.view) {
                const currentUrl = new URL(window.location.href)
                const shareUrl = new URL(currentUrl.origin + currentUrl.pathname)
                shareUrl.searchParams.set('open_view', currentTab.view.id)

                if (values.queryInput != currentTab.view.query.query) {
                    shareUrl.searchParams.set('open_query', values.queryInput ?? '')
                }

                void copyToClipboard(shareUrl.toString(), 'share link')
            } else {
                const currentUrl = new URL(window.location.href)
                const shareUrl = new URL(currentUrl.origin + currentUrl.pathname)
                shareUrl.searchParams.set('open_query', values.queryInput ?? '')

                void copyToClipboard(shareUrl.toString(), 'share link')
            }
        },
        setSuggestedQueryInput: ({ suggestedQueryInput, source }) => {
            // If there's no active tab, create one first to ensure Monaco Editor is available
            if (!values.activeTab) {
                actions.createTab(suggestedQueryInput)
                return
            }

            // Always create suggestion payload when a new suggestion comes in, even for consecutive suggestions
            // Only skip diff mode if the editor is completely empty
            if (values.queryInput && values.queryInput.trim() !== '') {
                actions._setSuggestionPayload({
                    suggestedValue: suggestedQueryInput,
                    originalValue: values.queryInput, // Store the current content as original for diff mode
                    acceptText: aiSuggestionOnAcceptText,
                    rejectText: aiSuggestionOnRejectText,
                    onAccept: aiSuggestionOnAccept,
                    onReject: aiSuggestionOnReject,
                    source,
                    diffShowRunButton: true,
                })
            } else {
                actions.setQueryInput(suggestedQueryInput)
            }
        },
        onAcceptSuggestedQueryInput: ({ shouldRunQuery }) => {
            values.suggestionPayload?.onAccept(!!shouldRunQuery, actions, values, props)

            // Re-create the model to prevent it from being purged
            if (props.monaco && values.activeTab) {
                const existingModel = props.monaco.editor.getModel(values.activeTab.uri)
                if (!existingModel) {
                    const newModel = props.monaco.editor.createModel(
                        values.suggestedQueryInput,
                        'hogQL',
                        values.activeTab.uri
                    )
                    cache.createdModels = cache.createdModels || []
                    cache.createdModels.push(newModel)

                    initModel(
                        newModel,
                        codeEditorLogic({
                            key: `hogql-editor-${props.tabId}`,
                            query: values.suggestedQueryInput,
                            language: 'hogQL',
                        })
                    )

                    // Handle both diff editor and regular editor
                    if (props.editor && 'getModifiedEditor' in props.editor) {
                        // It's a diff editor, set model on the modified editor
                        const modifiedEditor = (props.editor as any).getModifiedEditor()
                        modifiedEditor.setModel(newModel)
                    } else {
                        // Regular editor
                        props.editor?.setModel(newModel)
                    }
                } else {
                    // Handle both diff editor and regular editor
                    if (props.editor && 'getModifiedEditor' in props.editor) {
                        // It's a diff editor, set model on the modified editor
                        const modifiedEditor = (props.editor as any).getModifiedEditor()
                        modifiedEditor.setModel(existingModel)
                    } else {
                        // Regular editor
                        props.editor?.setModel(existingModel)
                    }
                }
            }
            posthog.capture('sql-editor-accepted-suggestion', { source: values.suggestedSource })
            actions._setSuggestionPayload(null)
        },
        onRejectSuggestedQueryInput: () => {
            values.suggestionPayload?.onReject(actions, values, props)

            // Re-create the model to prevent it from being purged
            if (props.monaco && values.activeTab) {
                const existingModel = props.monaco.editor.getModel(values.activeTab.uri)
                if (!existingModel) {
                    const newModel = props.monaco.editor.createModel(
                        values.queryInput ?? '',
                        'hogQL',
                        values.activeTab.uri
                    )
                    cache.createdModels = cache.createdModels || []
                    cache.createdModels.push(newModel)
                    initModel(
                        newModel,
                        codeEditorLogic({
                            key: `hogql-editor-${props.tabId}`,
                            query: values.queryInput ?? '',
                            language: 'hogQL',
                        })
                    )

                    // Handle both diff editor and regular editor
                    if (props.editor && 'getModifiedEditor' in props.editor) {
                        // It's a diff editor, set model on the modified editor
                        const modifiedEditor = (props.editor as any).getModifiedEditor()
                        modifiedEditor.setModel(newModel)
                    } else {
                        // Regular editor
                        props.editor?.setModel(newModel)
                    }
                } else {
                    // Handle both diff editor and regular editor
                    if (props.editor && 'getModifiedEditor' in props.editor) {
                        // It's a diff editor, set model on the modified editor
                        const modifiedEditor = (props.editor as any).getModifiedEditor()
                        modifiedEditor.setModel(existingModel)
                    } else {
                        // Regular editor
                        props.editor?.setModel(existingModel)
                    }
                }
            }
            posthog.capture('sql-editor-rejected-suggestion', { source: values.suggestedSource })
            actions._setSuggestionPayload(null)
        },
        editView: ({ query, view }) => {
            actions.createTab(query, view)
        },
        editInsight: ({ query, insight }) => {
            actions.createTab(query, undefined, insight)
        },
        createTab: async ({ query = '', view, insight, draft }) => {
            // Use tabId to ensure each browser tab has its own unique Monaco model
            const tabName = draft?.name || view?.name || insight?.name || NEW_QUERY

            if (props.monaco) {
                const uri = props.monaco.Uri.parse(`tab-${props.tabId}`)
                let model = props.monaco.editor.getModel(uri)
                if (!model) {
                    model = props.monaco.editor.createModel(query, 'hogQL', uri)
                    cache.createdModels = cache.createdModels || []
                    cache.createdModels.push(model)
                    props.editor?.setModel(model)
                    initModel(
                        model,
                        codeEditorLogic({
                            key: `hogql-editor-${props.tabId}`,
                            query: values.sourceQuery?.source.query ?? '',
                            language: 'hogQL',
                        })
                    )
                }

                actions.updateTab({
                    uri,
                    view,
                    insight,
                    name: tabName,
                    sourceQuery: insight?.query as DataVisualizationNode | undefined,
                    draft: draft,
                })
            }
            if (query) {
                actions.setQueryInput(query)
            } else if (draft) {
                actions.setQueryInput(draft.query.query)
            } else if (view) {
                actions.setQueryInput(view.query.query)
            } else if (insight) {
                const queryObject = (insight.query as DataVisualizationNode | null)?.source || insight.query
                if (queryObject && 'query' in queryObject) {
                    actions.setQueryInput(queryObject.query || '')
                }
            }
        },
        setSourceQuery: ({ sourceQuery }) => {
            if (!values.activeTab) {
                return
            }

            const currentTab = values.activeTab
            if (currentTab) {
                actions.updateTab({
                    ...currentTab,
                    sourceQuery,
                })
            }
        },
        initialize: async () => {
            actions.setFinishedLoading(false)
        },
        setQueryInput: ({ queryInput }) => {
            // Keep suggestion payload active - let user make edits and then decide to approve/reject
            // if editing a view, track latest history id changes are based on
            if (values.activeTab?.view && values.activeTab?.view.query?.query) {
                if (queryInput === values.activeTab.view?.query.query) {
                    actions.deleteInProgressViewEdit(values.activeTab.view.id)
                } else if (
                    !values.inProgressViewEdits[values.activeTab.view.id] &&
                    values.activeTab.view.latest_history_id
                ) {
                    actions.setInProgressViewEdit(values.activeTab.view.id, values.activeTab.view.latest_history_id)
                }
            }
        },
        saveDraft: async ({ activeTab, queryInput, viewId }) => {
            const latestActiveTab = values.allTabs.find((tab) => tab.uri.toString() === activeTab.uri.toString())

            if (latestActiveTab) {
                actions.saveAsDraft(
                    {
                        kind: NodeKind.HogQLQuery,
                        query: queryInput,
                    },
                    viewId,
                    latestActiveTab
                )
            }
        },
        saveAsDraftSuccess: ({ draft, tab: tabToUpdate }) => {
            actions.updateTab({ ...tabToUpdate, name: draft.name, draft: draft })
        },
        runQuery: ({ queryOverride, switchTab }) => {
            const query = (queryOverride || values.queryInput) ?? ''

            const newSource = {
                ...values.sourceQuery.source,
                query,
            }

            actions.setSourceQuery({
                ...values.sourceQuery,
                source: newSource,
            })
            actions.setLastRunQuery({
                ...values.sourceQuery,
                source: newSource,
            })
            if (!cache.umountDataNode) {
                cache.umountDataNode = dataNodeLogic({
                    key: values.dataLogicKey,
                    query: newSource,
                }).mount()
            }
            dataNodeLogic({
                key: values.dataLogicKey,
                query: newSource,
            }).actions.loadData(!switchTab ? 'force_async' : 'async')
        },
        saveAsView: async ({ fromDraft, materializeAfterSave = false }) => {
            LemonDialog.openForm({
                title: 'Save as view',
                initialValues: { viewName: values.activeTab?.name || '' },
                description: `View names can only contain letters, numbers, '_', or '$'. Spaces are not allowed.`,
                content: (isLoading) =>
                    isLoading ? (
                        <div className="h-[37px] flex items-center">
                            <ViewEmptyState />
                        </div>
                    ) : (
                        <LemonField name="viewName">
                            <LemonInput
                                data-attr="sql-editor-input-save-view-name"
                                disabled={isLoading}
                                placeholder="Please enter the name of the view"
                                autoFocus
                            />
                        </LemonField>
                    ),
                errors: {
                    viewName: (name) =>
                        !name
                            ? 'You must enter a name'
                            : !/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name)
                              ? 'Name must be valid'
                              : undefined,
                },
                onSubmit: async ({ viewName }) => {
                    await asyncActions.saveAsViewSubmit(viewName, materializeAfterSave, fromDraft)
                },
                shouldAwaitSubmit: true,
            })
        },
        saveAsViewSubmit: async ({ name, materializeAfterSave = false, fromDraft }) => {
            const query: HogQLQuery = values.sourceQuery.source

            const queryToSave = {
                ...query,
                query: values.queryInput ?? '',
            }

            const logic = dataNodeLogic({
                key: values.dataLogicKey,
                query: queryToSave,
            })

            const response = logic.values.response
            const types = response && 'types' in response ? (response.types ?? []) : []
            try {
                await dataWarehouseViewsLogic.asyncActions.createDataWarehouseSavedQuery({
                    name,
                    query: queryToSave,
                    types,
                })

                // Saved queries are unique by team,name
                const savedQuery = dataWarehouseViewsLogic.values.dataWarehouseSavedQueries.find((q) => q.name === name)

                if (materializeAfterSave && savedQuery) {
                    await dataWarehouseViewsLogic.asyncActions.updateDataWarehouseSavedQuery({
                        id: savedQuery.id,
                        sync_frequency: '24hour',
                        types: [[]],
                        lifecycle: 'create',
                    })
                }

                if (fromDraft) {
                    actions.deleteDraft(fromDraft, savedQuery?.name)
                }
            } catch {
                lemonToast.error('Failed to save view')
            }
        },
        saveAsInsight: async () => {
            LemonDialog.openForm({
                title: 'Save as new insight',
                initialValues: {
                    name: '',
                },
                content: (
                    <LemonField name="name">
                        <LemonInput data-attr="insight-name" placeholder="Please enter the new name" autoFocus />
                    </LemonField>
                ),
                errors: {
                    name: (name) => (!name ? 'You must enter a name' : undefined),
                },
                onSubmit: async ({ name }) => actions.saveAsInsightSubmit(name),
            })
        },
        saveAsInsightSubmit: async ({ name }) => {
            const insight = await insightsApi.create({
                name,
                query: values.sourceQuery,
                saved: true,
            })
            const logic = insightLogic({
                dashboardItemId: insight.short_id,
                doNotLoad: true,
            })
            const umount = logic.mount()
            logic.actions.setInsight(insight, { fromPersistentApi: true, overrideQuery: true })
            const timeoutId = window.setTimeout(() => umount(), 1000 * 10) // keep mounted for 10 seconds while we redirect
            cache.timeouts = cache.timeouts || []
            cache.timeouts.push(timeoutId)

            lemonToast.info(`You're now viewing ${insight.name || insight.derived_name || name}`)

            router.actions.push(urls.insightView(insight.short_id))
        },
        updateInsight: async () => {
            if (!values.editingInsight) {
                return
            }

            const insightName = values.activeTab?.name

            const insightRequest: Partial<QueryBasedInsightModel> = {
                name: insightName ?? values.editingInsight.name,
                query: values.sourceQuery,
            }

            const savedInsight = await insightsApi.update(values.editingInsight.id, insightRequest)

            if (values.activeTab) {
                actions.updateTab({
                    ...values.activeTab,
                    insight: savedInsight,
                })
            }
            const loadedLogic = insightLogic.findMounted({
                dashboardItemId: values.editingInsight.short_id,
                dashboardId: undefined,
            })
            if (loadedLogic) {
                loadedLogic.actions.setInsight(savedInsight, { overrideQuery: true, fromPersistentApi: true })
            }

            lemonToast.info(`You're now viewing ${savedInsight.name || savedInsight.derived_name || name}`)

            router.actions.push(urls.insightView(savedInsight.short_id))
        },
        loadDataWarehouseSavedQueriesSuccess: ({ dataWarehouseSavedQueries }) => {
            // keep tab views up to date
            const tab = values.activeTab
            const view = dataWarehouseSavedQueries.find((v) => v.id === tab.view?.id)
            if (tab && view) {
                actions.setTabs([{ ...tab, view }])
                actions.setQueryInput(view.query.query || '')
            }
        },
        deleteDataWarehouseSavedQuerySuccess: ({ payload: viewId }) => {
            const mustRemoveTab = values.allTabs.find((tab) => tab.view?.id === viewId && !tab.draft)
            if (mustRemoveTab) {
                actions.setTabs([])
                actions.createTab()
            }
            lemonToast.success('View deleted')
        },
        createDataWarehouseSavedQuerySuccess: ({ dataWarehouseSavedQueries, payload: view }) => {
            const newView = view && dataWarehouseSavedQueries.find((v) => v.name === view.name)
            if (newView) {
                const oldTab = values.activeTab
                if (oldTab) {
                    actions.updateTab({ ...oldTab, view: newView })
                }
            }
        },
        updateDataWarehouseSavedQuerySuccess: () => {
            lemonToast.success('View updated')
        },
        updateView: async ({ view, draftId }) => {
            const latestView = await api.dataWarehouseSavedQueries.get(view.id)
            // Only check for conflicts if there's an activity log (latest_history_id exists)
            // When there's no activity log, both edited_history_id and latest_history_id are null/undefined,
            // and we should allow the update to proceed without showing a false conflict
            if (
                latestView?.latest_history_id != null &&
                view.edited_history_id !== latestView.latest_history_id &&
                view.query?.query !== latestView?.query.query
            ) {
                actions._setSuggestionPayload({
                    suggestedValue: values.queryInput!,
                    originalValue: latestView?.query.query,
                    acceptText: 'Confirm changes',
                    rejectText: 'Cancel',
                    diffShowRunButton: false,
                    onAccept: async () => {
                        actions.setQueryInput(view.query?.query ?? '')
                        await dataWarehouseViewsLogic.asyncActions.updateDataWarehouseSavedQuery({
                            ...view,
                            edited_history_id: latestView?.latest_history_id,
                        })
                        actions.updateViewSuccess(view, draftId)
                    },
                    onReject: () => {},
                })
                lemonToast.error('View has been edited by another user. Review changes to update.')
            } else {
                await dataWarehouseViewsLogic.asyncActions.updateDataWarehouseSavedQuery(view)
                actions.updateViewSuccess(view, draftId)
            }
        },
        updateViewSuccess: ({ view, draftId }) => {
            if (draftId) {
                actions.deleteDraft(draftId, view?.name)
            }
        },
        deleteDraftSuccess: ({ draftId, viewName }) => {
            // remove draft from all tabs
            const newTabs = values.allTabs.map((tab) => ({
                ...tab,
                draft: tab.draft?.id === draftId ? undefined : tab.draft,
                name: tab.draft?.id === draftId && viewName ? viewName : tab.name,
            }))
            actions.setTabs(newTabs)
        },
    })),
    subscriptions(({ actions, values }) => ({
        showLegacyFilters: (showLegacyFilters: boolean) => {
            if (showLegacyFilters) {
                if (typeof values.sourceQuery.source.filters !== 'object') {
                    actions.setSourceQuery({
                        ...values.sourceQuery,
                        source: {
                            ...values.sourceQuery.source,
                            filters: {},
                        },
                    })
                }
            } else {
                if (values.sourceQuery.source.filters !== undefined) {
                    actions.setSourceQuery({
                        ...values.sourceQuery,
                        source: {
                            ...values.sourceQuery.source,
                            filters: undefined,
                        },
                    })
                }
            }
        },
        editingView: (editingView) => {
            if (editingView) {
                actions.resetDataModelingJobs()
                actions.loadDataModelingJobs(editingView.id)
                actions.loadUpstream(editingView.id)
            }
        },
        drafts: (drafts) => {
            // update all drafts in all tabs
            const newTabs = values.allTabs.map((tab) => ({
                ...tab,
                draft: drafts.find((d: DataWarehouseSavedQueryDraft) => d.id === tab.draft?.id),
                name:
                    drafts.find((d: DataWarehouseSavedQueryDraft) => d.id === tab.draft?.id)?.name ??
                    tab.view?.name ??
                    tab.name,
            }))
            actions.setTabs(newTabs)
        },
    })),
    selectors({
        activeTab: [(s) => [s.allTabs], (allTabs: QueryTab[]) => allTabs?.[0] ?? null],
        suggestedSource: [
            (s) => [s.suggestionPayload],
            (suggestionPayload) => {
                return suggestionPayload?.source ?? null
            },
        ],
        diffShowRunButton: [
            (s) => [s.suggestionPayload],
            (suggestionPayload) => {
                return suggestionPayload?.diffShowRunButton
            },
        ],
        acceptText: [
            (s) => [s.suggestionPayload],
            (suggestionPayload) => {
                return suggestionPayload?.acceptText ?? 'Accept'
            },
        ],
        rejectText: [
            (s) => [s.suggestionPayload],
            (suggestionPayload) => {
                return suggestionPayload?.rejectText ?? 'Reject'
            },
        ],

        suggestedQueryInput: [
            (s) => [s.suggestionPayload, s.queryInput],
            (suggestionPayload, queryInput) => {
                if (suggestionPayload?.suggestedValue && suggestionPayload?.suggestedValue !== queryInput) {
                    return suggestionPayload?.suggestedValue ?? ''
                }

                return queryInput ?? ''
            },
        ],
        originalQueryInput: [
            (s) => [s.suggestionPayload, s.queryInput],
            (suggestionPayload, queryInput) => {
                // If we have a suggestion payload, always show diff mode
                if (suggestionPayload?.suggestedValue) {
                    // Prefer the stored originalValue if available, otherwise use current queryInput
                    return suggestionPayload?.originalValue || queryInput
                }

                return undefined
            },
        ],
        editingView: [
            (s) => [s.activeTab],
            (activeTab) => {
                return activeTab?.view
            },
        ],
        changesToSave: [
            (s) => [s.editingView, s.queryInput],
            (editingView, queryInput) => {
                return editingView?.query?.query !== queryInput
            },
        ],
        exportContext: [
            (s) => [s.sourceQuery],
            (sourceQuery) => {
                // TODO: use active tab at some point
                const filename = 'export'

                return {
                    ...queryExportContext(sourceQuery.source, undefined, undefined),
                    filename,
                } as ExportContext
            },
        ],
        isEditingMaterializedView: [
            (s) => [s.editingView],
            (editingView) => {
                return !!editingView?.is_materialized
            },
        ],
        isSourceQueryLastRun: [
            (s) => [s.queryInput, s.lastRunQuery],
            (queryInput, lastRunQuery) => {
                return queryInput === lastRunQuery?.source.query
            },
        ],
        updateInsightButtonEnabled: [
            (s) => [s.sourceQuery, s.activeTab],
            (sourceQuery, activeTab) => {
                if (!activeTab?.insight?.query || !activeTab.sourceQuery) {
                    return false
                }

                const updatedName = activeTab.name !== activeTab.insight.name

                const sourceQueryWithoutUndefinedAndNullKeys = removeUndefinedAndNull(sourceQuery)

                return (
                    updatedName ||
                    !isEqual(sourceQueryWithoutUndefinedAndNullKeys, removeUndefinedAndNull(activeTab.insight.query))
                )
            },
        ],
        showLegacyFilters: [
            (s) => [s.queryInput],
            (queryInput) => {
                return queryInput && (queryInput.indexOf('{filters}') !== -1 || queryInput.indexOf('{filters.') !== -1)
            },
        ],
        dataLogicKey: [(_, p) => [p.tabId], (tabId) => `data-warehouse-editor-data-node-${tabId}`],
        isDraft: [(s) => [s.activeTab], (activeTab) => (activeTab ? !!activeTab.draft?.id : false)],
        currentDraft: [(s) => [s.activeTab], (activeTab) => (activeTab ? activeTab.draft : null)],
        breadcrumbs: [
            (s) => [s.activeTab],
            (activeTab): Breadcrumb[] => {
                const { draft, insight, view } = activeTab || {}
                const first = {
                    key: Scene.SQLEditor,
                    name: 'SQL query',
                    to: urls.sqlEditor(),
                    iconType: 'sql_editor' as FileSystemIconType,
                }
                if (view) {
                    return [
                        first,
                        {
                            key: view.id,
                            name: view.name,
                            path: urls.sqlEditor(undefined, view.id),
                            iconType: 'sql_editor',
                        },
                    ]
                } else if (insight) {
                    return [
                        first,
                        {
                            key: insight.id,
                            name: insight.name || insight.derived_name || 'Untitled',
                            path: urls.sqlEditor(undefined, undefined, insight.short_id),
                            iconType: 'sql_editor',
                        },
                    ]
                } else if (draft) {
                    return [
                        first,
                        {
                            key: draft.id,
                            name: draft.name || 'Untitled',
                            path: urls.sqlEditor(undefined, undefined, undefined, draft.id),
                            iconType: 'sql_editor',
                        },
                    ]
                }
                return [first]
            },
        ],
    }),
    tabAwareActionToUrl(({ values }) => ({
        setQueryInput: () => {
            return [urls.sqlEditor(), undefined, getTabHash(values), { replace: true }]
        },
        createTab: () => {
            return [urls.sqlEditor(), undefined, getTabHash(values), { replace: true }]
        },
    })),
    tabAwareUrlToAction(({ actions, values, props }) => ({
        [urls.sqlEditor()]: async (_, searchParams, hashParams) => {
            if (
                !searchParams.open_query &&
                !searchParams.open_view &&
                !searchParams.open_insight &&
                !searchParams.open_draft &&
                !searchParams.output_tab &&
                !hashParams.q &&
                !hashParams.view &&
                !hashParams.insight &&
                values.queryInput !== null
            ) {
                return
            }

            let tabAdded = false

            const createQueryTab = async (): Promise<void> => {
                if (searchParams.output_tab) {
                    actions.setActiveTab(searchParams.output_tab as OutputTab)
                }
                if (searchParams.open_draft || (hashParams.draft && values.queryInput === null)) {
                    const draftId = searchParams.open_draft || hashParams.draft
                    const draft = values.drafts.find((draft) => {
                        return draft.id === draftId
                    })

                    if (!draft) {
                        lemonToast.error('Draft not found')
                        return
                    }

                    const existingTab = values.allTabs.find((tab) => {
                        return tab.draft?.id === draft.id
                    })

                    if (!existingTab) {
                        const associatedView = draft.saved_query_id
                            ? values.dataWarehouseSavedQueryMapById[draft.saved_query_id]
                            : undefined

                        actions.createTab(draft.query.query, associatedView, undefined, draft)

                        const newTab = values.allTabs[values.allTabs.length - 1]
                        if (newTab) {
                            actions.setTabDraftId(newTab.uri.toString(), draft.id)
                        }
                    }
                    return
                } else if (searchParams.open_view || (hashParams.view && values.queryInput === null)) {
                    // Open view
                    const viewId = searchParams.open_view || hashParams.view

                    if (values.dataWarehouseSavedQueries.length === 0) {
                        await dataWarehouseViewsLogic.asyncActions.loadDataWarehouseSavedQueries()
                    }

                    const view = values.dataWarehouseSavedQueries.find((n) => n.id === viewId)
                    if (!view) {
                        lemonToast.error('View not found')
                        return
                    }

                    const queryToOpen = searchParams.open_query ? searchParams.open_query : view.query.query

                    actions.editView(queryToOpen, view)
                    tabAdded = true
                    router.actions.replace(urls.sqlEditor(), undefined, getTabHash(values))
                } else if (searchParams.open_insight || (hashParams.insight && values.queryInput === null)) {
                    const shortId = searchParams.open_insight || hashParams.insight
                    if (shortId === 'new') {
                        // Add new blank tab
                        actions.createTab()
                        tabAdded = true
                        router.actions.replace(urls.sqlEditor(), undefined, getTabHash(values))
                        return
                    }

                    // Open Insight
                    const insight = await insightsApi.getByShortId(shortId, undefined, 'async')
                    if (!insight) {
                        lemonToast.error('Insight not found')
                        return
                    }

                    let query = ''
                    if (insight.query?.kind === NodeKind.DataVisualizationNode) {
                        query = (insight.query as DataVisualizationNode).source.query
                    }

                    const queryToOpen = searchParams.open_query ? searchParams.open_query : query

                    actions.editInsight(queryToOpen, insight)
                    if (insight.query) {
                        actions.setSourceQuery(insight.query as DataVisualizationNode)
                    }
                    actions.setActiveTab(OutputTab.Visualization)

                    // Only run the query if the results aren't already cached locally and we're not using the open_query search param
                    if (
                        insight.query?.kind === NodeKind.DataVisualizationNode &&
                        insight.query &&
                        !searchParams.open_query
                    ) {
                        dataNodeLogic({
                            key: values.dataLogicKey,
                            query: (insight.query as DataVisualizationNode).source,
                        }).mount()

                        const response = dataNodeLogic({
                            key: values.dataLogicKey,
                            query: (insight.query as DataVisualizationNode).source,
                        }).values.response

                        if (!response) {
                            actions.runQuery()
                        }
                    } else {
                        actions.runQuery()
                    }

                    tabAdded = true
                    router.actions.replace(urls.sqlEditor(), undefined, getTabHash(values))
                } else if (searchParams.open_query) {
                    // Open query string
                    actions.createTab(searchParams.open_query)
                    tabAdded = true
                } else if (hashParams.q && values.queryInput === null) {
                    // only when opening the tab
                    actions.createTab(hashParams.q)
                    tabAdded = true
                } else if (values.queryInput === null) {
                    actions.createTab('')
                    tabAdded = true
                }
            }

            if (props.monaco) {
                await createQueryTab()
            } else {
                const waitUntilMonaco = async (): Promise<void> => {
                    return await new Promise((resolve, reject) => {
                        let intervalCount = 0
                        const interval = setInterval(() => {
                            intervalCount++

                            if (props.monaco && !tabAdded) {
                                clearInterval(interval)
                                resolve()
                            } else if (intervalCount >= 10_000 / 300) {
                                clearInterval(interval)
                                reject()
                            }
                        }, 300)
                    })
                }

                await waitUntilMonaco().then(async () => {
                    await createQueryTab()
                })
            }
        },
    })),
    beforeUnmount(({ cache }) => {
        cache.umountDataNode?.()

        cache.createdModels?.forEach((m: editor.ITextModel) => {
            try {
                m.dispose()
            } catch {}
        })
        cache.createdModels = []

        const timeouts = cache.timeouts as Array<number> | undefined
        timeouts?.forEach((t) => {
            try {
                clearTimeout(t)
            } catch {}
        })
        cache.timeouts = []
    }),
])
