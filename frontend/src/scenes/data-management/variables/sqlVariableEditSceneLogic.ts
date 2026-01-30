import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { Variable, VariableType } from '~/queries/nodes/DataVisualization/types'

import type { sqlVariableEditSceneLogicType } from './sqlVariableEditSceneLogicType'

export interface SqlVariableEditSceneLogicProps {
    id: string
}

const NEW_VARIABLE_DEFAULTS: Partial<Variable> = {
    name: '',
    type: 'String',
    default_value: '',
}

export const sqlVariableEditSceneLogic = kea<sqlVariableEditSceneLogicType>([
    props({} as SqlVariableEditSceneLogicProps),
    path(['scenes', 'data-management', 'variables', 'sqlVariableEditSceneLogic']),
    key((props: SqlVariableEditSceneLogicProps) => props.id),
    actions({
        setVariableType: (type: VariableType) => ({ type }),
    }),
    loaders(({ props }) => ({
        variable: [
            null as Variable | null,
            {
                loadVariable: async () => {
                    if (props.id === 'new') {
                        return null
                    }
                    try {
                        const response = await api.insightVariables.list()
                        return response.results.find((v: Variable) => v.id === props.id) ?? null
                    } catch {
                        return null
                    }
                },
            },
        ],
    })),
    reducers({
        variableType: [
            'String' as VariableType,
            {
                setVariableType: (_, { type }: { type: VariableType }) => type,
                loadVariableSuccess: (state: VariableType, { variable }: { variable: Variable | null }) =>
                    variable?.type ?? state,
            },
        ],
    }),
    forms(({ props, values }) => ({
        variableForm: {
            defaults: NEW_VARIABLE_DEFAULTS as Partial<Variable>,
            errors: ({ name }: { name?: string }) => ({
                name: !name?.trim() ? 'Name is required' : undefined,
            }),
            submit: async (formValues: Partial<Variable>) => {
                const data: Partial<Variable> = {
                    ...formValues,
                    type: values.variableType,
                }

                try {
                    if (props.id === 'new') {
                        await api.insightVariables.create(data)
                        lemonToast.success('Variable created')
                    } else {
                        await api.insightVariables.update(props.id, data)
                        lemonToast.success('Variable updated')
                    }
                    router.actions.push(urls.variables())
                } catch (error: unknown) {
                    const apiError = error as { data?: { detail?: string } }
                    if (apiError.data?.detail) {
                        lemonToast.error(apiError.data.detail)
                    } else {
                        lemonToast.error('Failed to save variable')
                    }
                    throw error
                }
            },
        },
    })),
    selectors({
        isNew: [(_, p) => [p.id], (id: string): boolean => id === 'new'],
        breadcrumbs: [
            (s, p) => [s.variable, p.id],
            (variable: Variable | null, id: string) => [
                {
                    key: 'variables',
                    name: 'SQL variables',
                    path: urls.variables(),
                },
                {
                    key: 'variable',
                    name: id === 'new' ? 'New variable' : (variable?.name ?? 'Loading...'),
                },
            ],
        ],
    }),
    listeners(({ actions }) => ({
        loadVariableSuccess: ({ variable }: { variable: Variable | null }) => {
            if (variable) {
                actions.setVariableFormValues({
                    name: variable.name,
                    type: variable.type,
                    default_value: variable.default_value,
                    values: variable.type === 'List' ? (variable as any).values : undefined,
                })
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadVariable()
    }),
])
