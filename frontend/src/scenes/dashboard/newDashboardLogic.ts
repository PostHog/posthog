import { actions, connect, isBreakpoint, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'
import { legacyEntityToNode, sanitizeRetentionEntity } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { getQueryBasedDashboard } from '~/queries/nodes/InsightViz/utils'
import { NodeKind } from '~/queries/schema/schema-general'
import { isInsightVizNode } from '~/queries/utils'
import { DashboardTemplateType, DashboardTemplateVariableType, DashboardTile, DashboardType, JsonType } from '~/types'

import type { newDashboardLogicType } from './newDashboardLogicType'

export interface NewDashboardForm {
    name: string
    description: ''
    show: boolean
    useTemplate: string
    _create_in_folder?: string | null
}

const defaultFormValues: NewDashboardForm = {
    name: '',
    description: '',
    show: false,
    useTemplate: '',
}

export interface NewDashboardLogicProps {
    featureFlagId?: number
    initialTags?: string[]
}

// Currently this is a very generic recursive function incase we want to add template variables to aspects beyond events
export function applyTemplate(
    obj: DashboardTile | JsonType,
    variables: DashboardTemplateVariableType[],
    queryKind: NodeKind | null
): JsonType {
    if (typeof obj === 'string') {
        if (obj.startsWith('{') && obj.endsWith('}')) {
            const variableId = obj.substring(1, obj.length - 1)
            const variable = variables.find((variable) => variable.id === variableId)
            if (variable && variable.default) {
                // added for future compatibility - at the moment we only have event variables
                const isEventVariable = variable.type === 'event'

                if (queryKind && isEventVariable) {
                    let mathAvailability = MathAvailability.None
                    if (queryKind === NodeKind.TrendsQuery) {
                        mathAvailability = MathAvailability.All
                    } else if (queryKind === NodeKind.StickinessQuery) {
                        mathAvailability = MathAvailability.ActorsOnly
                    } else if (queryKind === NodeKind.FunnelsQuery) {
                        mathAvailability = MathAvailability.FunnelsOnly
                    }
                    return (
                        queryKind === NodeKind.RetentionQuery
                            ? sanitizeRetentionEntity(variable.default as any)
                            : legacyEntityToNode(variable.default as any, true, mathAvailability)
                    ) as JsonType
                }

                return variable.default as JsonType
            }
            return obj
        }
    }
    if (Array.isArray(obj)) {
        return obj.map((item) => applyTemplate(item, variables, queryKind))
    }
    if (typeof obj === 'object' && obj !== null) {
        const newObject: JsonType = {}
        for (const [key, value] of Object.entries(obj)) {
            newObject[key] = applyTemplate(value, variables, queryKind)
        }
        return newObject
    }
    return obj
}

function makeTilesUsingVariables(tiles: DashboardTile[], variables: DashboardTemplateVariableType[]): JsonType[] {
    return tiles.map((tile: DashboardTile) => {
        const isQueryBased = 'query' in tile && tile.query != null
        const queryKind: NodeKind | null = isQueryBased
            ? isInsightVizNode(tile.query as any)
                ? (tile.query as any)?.source.kind
                : (tile.query as any)?.kind
            : null
        return applyTemplate(tile, variables, queryKind)
    })
}

export const newDashboardLogic = kea<newDashboardLogicType>([
    props({} as NewDashboardLogicProps),
    key(({ featureFlagId }) => featureFlagId ?? 'new'),
    path(['scenes', 'dashboard', 'newDashboardLogic']),
    connect(() => ({
        logic: [dashboardsModel],
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
        showNewDashboardModal: true,
        showVariableSelectModal: (template: DashboardTemplateType) => ({ template }),
        hideNewDashboardModal: true,
        addDashboard: (form: Partial<NewDashboardForm>) => ({ form }),
        setActiveDashboardTemplate: (template: DashboardTemplateType) => ({ template }),
        clearActiveDashboardTemplate: true,
        createDashboardFromTemplate: (
            template: DashboardTemplateType,
            variables: DashboardTemplateVariableType[],
            redirectAfterCreation?: boolean,
            creationContext: string | null = null
        ) => ({
            template,
            variables,
            redirectAfterCreation,
            creationContext,
        }),
        submitNewDashboardSuccessWithResult: (result: DashboardType, variables?: DashboardTemplateVariableType[]) => ({
            result,
            variables,
        }),
    }),
    reducers({
        isLoading: [
            false,
            {
                setIsLoading: (_, { isLoading }) => isLoading,
                hideNewDashboardModal: () => false,
                submitNewDashboardSuccess: () => false,
                submitNewDashboardFailure: () => false,
                clearActiveDashboardTemplate: () => false,
            },
        ],
        newDashboardModalVisible: [
            false,
            {
                showNewDashboardModal: () => true,
                showVariableSelectModal: () => true,
                hideNewDashboardModal: () => false,
            },
        ],
        variableSelectModalVisible: [
            false,
            {
                showVariableSelectModal: () => true,
                hideNewDashboardModal: () => false,
            },
        ],
        activeDashboardTemplate: [
            null as DashboardTemplateType | null,
            {
                setActiveDashboardTemplate: (_, { template }) => template,
                clearActiveDashboardTemplate: () => null,
            },
        ],
    }),
    forms(({ actions, props }) => ({
        newDashboard: {
            defaults: defaultFormValues,
            errors: ({ name }) => ({
                name: !name ? 'Please give your dashboard a name.' : null,
            }),
            submit: async ({ name, description, useTemplate, show, _create_in_folder }, breakpoint) => {
                actions.setIsLoading(true)
                try {
                    const result: DashboardType = await api.create(
                        `api/environments/${teamLogic.values.currentTeamId}/dashboards/`,
                        {
                            name: name,
                            description: description,
                            use_template: useTemplate,
                            ...(props.initialTags && { tags: props.initialTags }),
                            ...(typeof _create_in_folder === 'string' ? { _create_in_folder } : {}),
                        } as Partial<DashboardType>
                    )
                    actions.hideNewDashboardModal()
                    actions.resetNewDashboard()
                    const queryBasedDashboard = getQueryBasedDashboard(result)
                    queryBasedDashboard && dashboardsModel.actions.addDashboardSuccess(queryBasedDashboard)
                    actions.submitNewDashboardSuccessWithResult(result)
                    if (show) {
                        breakpoint()
                        router.actions.push(urls.dashboard(result.id))
                    }
                } catch (e: any) {
                    if (!isBreakpoint(e)) {
                        const message = e.code && e.detail ? `${e.code}: ${e.detail}` : e
                        lemonToast.error(`Could not create dashboard: ${message}`)
                    }
                }
                actions.setIsLoading(false)
            },
        },
    })),
    selectors(({ props }) => ({
        isFeatureFlagDashboard: [() => [], () => props.featureFlagId],
    })),
    listeners(({ actions }) => ({
        addDashboard: ({ form }) => {
            actions.resetNewDashboard()
            actions.setNewDashboardValues({ ...defaultFormValues, ...form })
            actions.submitNewDashboard()
        },
        showNewDashboardModal: () => {
            actions.resetNewDashboard()
        },
        hideNewDashboardModal: () => {
            actions.clearActiveDashboardTemplate()
            actions.resetNewDashboard()
        },
        createDashboardFromTemplate: async ({
            template,
            variables,
            redirectAfterCreation = true,
            creationContext = null,
        }) => {
            actions.setIsLoading(true)
            const tiles = makeTilesUsingVariables(template.tiles, variables)
            const dashboardJSON = {
                ...template,
                tiles,
            }

            try {
                actions.hideNewDashboardModal()
                const result: DashboardType = await api.create(
                    `api/environments/${teamLogic.values.currentTeamId}/dashboards/create_from_template_json`,
                    {
                        template: dashboardJSON,
                        creation_context: creationContext,
                        _create_in_folder: 'Unfiled/Dashboards',
                    }
                )

                actions.resetNewDashboard()
                const queryBasedDashboard = getQueryBasedDashboard(result)
                queryBasedDashboard && dashboardsModel.actions.addDashboardSuccess(queryBasedDashboard)
                actions.submitNewDashboardSuccessWithResult(result, variables)
                if (redirectAfterCreation) {
                    router.actions.push(urls.dashboard(result.id))
                }
            } catch (e: any) {
                if (!isBreakpoint(e)) {
                    const message = e.code && e.detail ? `${e.code}: ${e.detail}` : e
                    lemonToast.error(`Could not create dashboard: ${message}`)
                }
            }
            actions.setIsLoading(false)
        },
        showVariableSelectModal: ({ template }) => {
            actions.setActiveDashboardTemplate(template)
        },
    })),
    urlToAction(({ actions }) => ({
        '/dashboard': (_, _searchParams, hashParams) => {
            if ('newDashboard' in hashParams) {
                actions.showNewDashboardModal()
            }
        },
    })),
    actionToUrl({
        hideNewDashboardModal: () => {
            const hashParams = router.values.hashParams
            delete hashParams['newDashboard']
            return [router.values.location.pathname, router.values.searchParams, hashParams]
        },
        showNewDashboardModal: () => {
            const hashParams = router.values.hashParams
            hashParams['newDashboard'] = 'modal'
            return [router.values.location.pathname, router.values.searchParams, hashParams]
        },
    }),
])
