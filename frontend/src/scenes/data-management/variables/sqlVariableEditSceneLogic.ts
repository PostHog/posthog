import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Variable, VariableType } from '~/queries/nodes/DataVisualization/types'
import { QueryBasedInsightModel } from '~/types'

import { fetchInsightsUsingVariable } from './insightsLoader'
import type { sqlVariableEditSceneLogicType } from './sqlVariableEditSceneLogicType'

export interface SqlVariableEditSceneLogicProps {
    id: string
}

const NEW_VARIABLE_DEFAULTS: Partial<Variable> = {
    name: '',
    type: 'String',
    default_value: '',
    code_name: '',
}

export const sqlVariableEditSceneLogic = kea<sqlVariableEditSceneLogicType>([
    props({} as SqlVariableEditSceneLogicProps),
    path(['scenes', 'data-management', 'variables', 'sqlVariableEditSceneLogic']),
    key((props: SqlVariableEditSceneLogicProps) => props.id),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),
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
        insightsUsingVariable: [
            [] as QueryBasedInsightModel[],
            {
                loadInsightsUsingVariable: async () => {
                    if (props.id === 'new') {
                        return []
                    }

                    const currentTeamId = teamLogic.values.currentTeamId
                    if (!currentTeamId) {
                        return []
                    }

                    try {
                        return await fetchInsightsUsingVariable(currentTeamId, props.id)
                    } catch {
                        // Error already handled by fetchInsightsUsingVariable
                        return []
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
    forms(({ props, values, actions }) => ({
        variableForm: {
            defaults: NEW_VARIABLE_DEFAULTS as Partial<Variable>,
            errors: ({ name }: { name?: string }) => ({
                name: !name?.trim() ? 'Name is required' : undefined,
            }),
            submit: async (formValues: Partial<Variable>) => {
                // TypeScript struggles with discriminated unions in Partial types,
                // but the form validation ensures this data is valid
                const data = {
                    ...formValues,
                    type: values.variableType,
                } as Partial<Variable>

                try {
                    if (props.id === 'new') {
                        const created = await api.insightVariables.create(data)
                        lemonToast.success('Variable created')
                        router.actions.push(urls.variableEdit(created.id))
                    } else {
                        await api.insightVariables.update(props.id, data)
                        lemonToast.success('Variable updated')
                        actions.loadVariable()
                    }
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
        hasChanges: [
            (s) => [s.variableForm, s.variableType, s.variable, s.variableLoading],
            (
                variableForm: Partial<Variable>,
                variableType: VariableType,
                variable: Variable | null,
                variableLoading: boolean
            ): boolean => {
                if (!variable || variableLoading) {
                    return false
                }
                const defaultValueForm = variableForm.default_value ?? ''
                const defaultValueSaved = variable.default_value ?? ''
                return (
                    (variableForm.name ?? '') !== (variable.name ?? '') ||
                    variableType !== variable.type ||
                    JSON.stringify(defaultValueForm) !== JSON.stringify(defaultValueSaved) ||
                    JSON.stringify((variableForm as any).values ?? null) !==
                        JSON.stringify((variable as any).values ?? null)
                )
            },
        ],
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
                // TypeScript can't narrow discriminated union types properly here,
                // but we know the data is valid since it comes from a typed Variable object
                const formValues = {
                    name: variable.name,
                    type: variable.type,
                    default_value: variable.default_value,
                    code_name: variable.code_name,
                    ...(variable.type === 'List' && { values: (variable as any).values }),
                } as Partial<Variable>

                actions.resetVariableForm(formValues)
                actions.loadInsightsUsingVariable()
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadVariable()
    }),
])
