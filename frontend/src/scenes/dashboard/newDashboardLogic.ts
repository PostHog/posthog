import { actions, connect, isBreakpoint, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { DashboardRestrictionLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'
import { getQueryBasedDashboard } from '~/queries/nodes/InsightViz/utils'
import { DashboardTemplateType, DashboardTemplateVariableType, DashboardTile, DashboardType, JsonType } from '~/types'

import type { newDashboardLogicType } from './newDashboardLogicType'

export interface NewDashboardForm {
    name: string
    description: ''
    show: boolean
    useTemplate: string
    restrictionLevel: DashboardRestrictionLevel
}

const defaultFormValues: NewDashboardForm = {
    name: '',
    description: '',
    show: false,
    useTemplate: '',
    restrictionLevel: DashboardRestrictionLevel.EveryoneInProjectCanEdit,
}

export interface NewDashboardLogicProps {
    featureFlagId?: number
}

// Currently this is a very generic recursive function incase we want to add template variables to aspects beyond events
export function applyTemplate(obj: DashboardTile | JsonType, variables: DashboardTemplateVariableType[]): JsonType {
    if (typeof obj === 'string') {
        if (obj.startsWith('{') && obj.endsWith('}')) {
            const variableId = obj.substring(1, obj.length - 1)
            const variable = variables.find((variable) => variable.id === variableId)
            if (variable && variable.default) {
                return variable.default
            }
            return obj
        }
    }
    if (Array.isArray(obj)) {
        return obj.map((item) => applyTemplate(item, variables))
    }
    if (typeof obj === 'object' && obj !== null) {
        const newObject: JsonType = {}
        for (const [key, value] of Object.entries(obj)) {
            newObject[key] = applyTemplate(value, variables)
        }
        return newObject
    }
    return obj
}

function makeTilesUsingVariables(tiles: DashboardTile[], variables: DashboardTemplateVariableType[]): JsonType[] {
    return tiles.map((tile: DashboardTile) => applyTemplate(tile, variables))
}

export const newDashboardLogic = kea<newDashboardLogicType>([
    props({} as NewDashboardLogicProps),
    key(({ featureFlagId }) => featureFlagId ?? 'new'),
    path(['scenes', 'dashboard', 'newDashboardLogic']),
    connect({ logic: [dashboardsModel], values: [featureFlagLogic, ['featureFlags']] }),
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
            redirectAfterCreation?: boolean
        ) => ({
            template,
            variables,
            redirectAfterCreation,
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
    forms(({ actions }) => ({
        newDashboard: {
            defaults: defaultFormValues,
            errors: ({ name, restrictionLevel }) => ({
                name: !name ? 'Please give your dashboard a name.' : null,
                restrictionLevel: !restrictionLevel ? 'Restriction level needs to be specified.' : null,
            }),
            submit: async ({ name, description, useTemplate, restrictionLevel, show }, breakpoint) => {
                actions.setIsLoading(true)
                try {
                    const result: DashboardType = await api.create(
                        `api/projects/${teamLogic.values.currentTeamId}/dashboards/`,
                        {
                            name: name,
                            description: description,
                            use_template: useTemplate,
                            restriction_level: restrictionLevel,
                        } as Partial<DashboardType>
                    )
                    actions.hideNewDashboardModal()
                    actions.resetNewDashboard()
                    dashboardsModel.actions.addDashboardSuccess(getQueryBasedDashboard(result))
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
        createDashboardFromTemplate: async ({ template, variables, redirectAfterCreation = true }) => {
            actions.setIsLoading(true)
            const tiles = makeTilesUsingVariables(template.tiles, variables)
            const dashboardJSON = {
                ...template,
                tiles,
            }

            try {
                const result: DashboardType = await api.create(
                    `api/projects/${teamLogic.values.currentTeamId}/dashboards/create_from_template_json`,
                    { template: dashboardJSON }
                )
                actions.hideNewDashboardModal()
                actions.resetNewDashboard()
                dashboardsModel.actions.addDashboardSuccess(getQueryBasedDashboard(result))
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
