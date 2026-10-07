import {
    MakeLogicType,
    actions,
    connect,
    isBreakpoint,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { tryShowMCPHint } from 'lib/components/MCPHint/mcpHintLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/types'
import { autoRunMaxPrompt } from 'scenes/max/maxPrompt'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import {
    legacyEntityToNode,
    sanitizeRetentionEntity,
} from '~/queries/nodes/InsightQuery/utils/actionsAndEventsToSeries'
import { getQueryBasedDashboard } from '~/queries/nodes/InsightViz/utils'
import { NodeKind } from '~/queries/schema/schema-general'
import { isInsightVizNode } from '~/queries/utils'
import {
    DashboardTemplateStoredTile,
    DashboardTemplateType,
    DashboardTemplateVariableType,
    DashboardTile,
    DashboardType,
    JsonType,
    SidePanelTab,
} from '~/types'

import { WEBSITE_METRICS_METRIC_CARD_TILES } from 'products/dashboards/frontend/websiteMetricsMetricCardTemplate'

import { UNFILED_DASHBOARDS_FOLDER } from './dashboardConstants'

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
    obj: DashboardTile | DashboardTemplateStoredTile | JsonType,
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

const METRIC_CARD_TEMPLATE_NAME = 'Website Metrics'

// A global scope alone does not identify the built-in: staff can promote a project template, which keeps its team_id.
function isMetricTemplate(template: DashboardTemplateType): boolean {
    return (
        template.scope === 'global' && template.team_id == null && template.template_name === METRIC_CARD_TEMPLATE_NAME
    )
}

function makeTilesUsingVariables(
    tiles: DashboardTemplateStoredTile[],
    variables: DashboardTemplateVariableType[]
): JsonType[] {
    return tiles.map((tile) => {
        const isQueryBased = 'query' in tile && (tile as { query?: unknown }).query != null
        const query = isQueryBased ? (tile as { query: unknown }).query : null
        const queryKind: NodeKind | null = isQueryBased
            ? isInsightVizNode(query as any)
                ? (query as any)?.source.kind
                : (query as any)?.kind
            : null
        return applyTemplate(tile, variables, queryKind)
    })
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface newDashboardLogicValues {
    activeDashboardTemplate: DashboardTemplateType | null
    isFeatureFlagDashboard: number | undefined
    isLoading: boolean
    isNewDashboardSubmitting: boolean
    isNewDashboardValid: boolean
    newDashboard: NewDashboardForm
    newDashboardAllErrors: Record<string, any>
    newDashboardChanged: boolean
    newDashboardErrors: DeepPartialMap<NewDashboardForm, ValidationErrorType>
    newDashboardHasErrors: boolean
    newDashboardManualErrors: Record<string, any>
    newDashboardModalVisible: boolean
    newDashboardTouched: boolean
    newDashboardTouches: Record<string, boolean>
    newDashboardValidationErrors: DeepPartialMap<NewDashboardForm, ValidationErrorType>
    openAIAfterCreation: boolean
    redirectAfterCreation: boolean
    setAsHomeTabDashboardAfterCreation: boolean
    showNewDashboardErrors: boolean
    variableSelectModalVisible: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface newDashboardLogicActions {
    addDashboard: (form: Partial<NewDashboardForm>) => {
        form: Partial<NewDashboardForm>
    }
    clearActiveDashboardTemplate: () => {
        value: true
    }
    createDashboardFromTemplate: (
        template: DashboardTemplateType,
        variables: DashboardTemplateVariableType[],
        redirectAfterCreation?: boolean,
        creationContext?: string | null
    ) => {
        creationContext: string | null
        redirectAfterCreation: boolean | undefined
        template: DashboardTemplateType
        variables: DashboardTemplateVariableType[]
    }
    hideNewDashboardModal: () => {
        value: true
    }
    resetNewDashboard: (values?: NewDashboardForm) => {
        values?: NewDashboardForm
    }
    setActiveDashboardTemplate: (template: DashboardTemplateType) => {
        template: DashboardTemplateType
    }
    setAsHomeTabDashboardAfterCreation: (
        setAsHomeTabDashboard: boolean,
        openAI?: boolean
    ) => {
        openAI: boolean
        setAsHomeTabDashboard: boolean
    }
    setIsLoading: (isLoading: boolean) => {
        isLoading: boolean
    }
    setNewDashboardManualErrors: (errors: Record<string, any>) => {
        errors: Record<string, any>
    }
    setNewDashboardValue: (
        key: FieldName,
        value: any
    ) => {
        name: FieldName
        value: any
    }
    setNewDashboardValues: (values: DeepPartial<NewDashboardForm>) => {
        values: DeepPartial<NewDashboardForm>
    }
    setRedirectAfterCreation: (redirect: boolean) => {
        redirect: boolean
    }
    showNewDashboardModal: () => {
        value: true
    }
    showVariableSelectModal: (template: DashboardTemplateType) => {
        template: DashboardTemplateType
    }
    submitNewDashboard: () => {
        value: boolean
    }
    submitNewDashboardFailure: (
        error: Error,
        errors: Record<string, any>
    ) => {
        error: Error
        errors: Record<string, any>
    }
    submitNewDashboardRequest: (newDashboard: NewDashboardForm) => {
        newDashboard: NewDashboardForm
    }
    submitNewDashboardSuccess: (newDashboard: NewDashboardForm) => {
        newDashboard: NewDashboardForm
    }
    submitNewDashboardSuccessWithResult: (
        result: DashboardType,
        variables?: DashboardTemplateVariableType[],
        setAsHomeTabDashboard?: boolean,
        openAI?: boolean
    ) => {
        openAI: boolean | undefined
        result: DashboardType
        setAsHomeTabDashboard: boolean | undefined
        variables: DashboardTemplateVariableType[] | undefined
    }
    touchNewDashboardField: (key: string) => {
        key: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface newDashboardLogicMeta {
    key: number | 'new'
}

export type newDashboardLogicType = MakeLogicType<
    newDashboardLogicValues,
    newDashboardLogicActions,
    NewDashboardLogicProps,
    newDashboardLogicMeta
>

export const newDashboardLogic = kea<newDashboardLogicType>([
    props({} as NewDashboardLogicProps),
    key(({ featureFlagId }) => featureFlagId ?? 'new'),
    path(['scenes', 'dashboard', 'newDashboardLogic']),
    connect(() => ({
        logic: [dashboardsModel],
    })),
    actions({
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
        showNewDashboardModal: true,
        showVariableSelectModal: (template: DashboardTemplateType) => ({ template }),
        hideNewDashboardModal: true,
        addDashboard: (form: Partial<NewDashboardForm>) => ({ form }),
        setActiveDashboardTemplate: (template: DashboardTemplateType) => ({ template }),
        clearActiveDashboardTemplate: true,
        setRedirectAfterCreation: (redirect: boolean) => ({ redirect }),
        setAsHomeTabDashboardAfterCreation: (setAsHomeTabDashboard: boolean, openAI: boolean = false) => ({
            setAsHomeTabDashboard,
            openAI,
        }),
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
        submitNewDashboardSuccessWithResult: (
            result: DashboardType,
            variables?: DashboardTemplateVariableType[],
            setAsHomeTabDashboard?: boolean,
            openAI?: boolean
        ) => ({ result, variables, setAsHomeTabDashboard, openAI }),
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
        redirectAfterCreation: [
            true,
            {
                setRedirectAfterCreation: (_, { redirect }) => redirect,
                showNewDashboardModal: () => true,
            },
        ],
        setAsHomeTabDashboardAfterCreation: [
            false,
            {
                setAsHomeTabDashboardAfterCreation: (_, { setAsHomeTabDashboard }) => setAsHomeTabDashboard,
                hideNewDashboardModal: () => false,
            },
        ],
        openAIAfterCreation: [
            false,
            {
                setAsHomeTabDashboardAfterCreation: (_, { openAI }) => openAI,
                hideNewDashboardModal: () => false,
            },
        ],
    }),
    forms(({ actions, props, values }) => ({
        newDashboard: {
            defaults: defaultFormValues,
            errors: ({ name }) => ({
                name: !name ? 'Please give your dashboard a name.' : null,
            }),
            submit: async ({ name, description, useTemplate, show, _create_in_folder }, breakpoint) => {
                actions.setIsLoading(true)
                // Read before the await: the modal/menu that mounts this logic can close
                // mid-request (e.g. the "Start from scratch" menu), unmounting it. Reading
                // `values` afterwards throws `[KEA] Can not find path`, which the catch below
                // would mislabel as "Could not create dashboard" even though creation succeeded.
                const redirectAfterCreation = values.redirectAfterCreation
                const setAsHomeTabDashboard = values.setAsHomeTabDashboardAfterCreation
                const openAI = values.openAIAfterCreation
                try {
                    // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. Use dashboardsCreate() from 'products/dashboards/frontend/generated/api' instead.
                    const result: DashboardType = await api.create(
                        `api/projects/${teamLogic.values.currentTeamId}/dashboards/`,
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
                    actions.submitNewDashboardSuccessWithResult(result, undefined, setAsHomeTabDashboard, openAI)
                    tryShowMCPHint('dashboards.create', {
                        derivedPrompt: result.name ? `Build a dashboard called ${result.name}` : undefined,
                    })
                    if (show && redirectAfterCreation) {
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
        showVariableSelectModal: ({ template }) => {
            actions.setActiveDashboardTemplate(template)
        },
        submitNewDashboardSuccessWithResult: async ({ result, setAsHomeTabDashboard, openAI }) => {
            if (setAsHomeTabDashboard) {
                try {
                    await teamLogic.asyncActions.updateCurrentTeam({ home_tab_dashboard: result.id })
                    // Loader failures finish asyncActions without throwing, so confirm the saved selection.
                    if (teamLogic.values.currentTeam?.home_tab_dashboard !== result.id) {
                        lemonToast.error('Could not set this dashboard as Home. Please try again.')
                        return
                    }
                } catch {
                    lemonToast.error('Could not set this dashboard as Home. Please try again.')
                    return
                }
            }
            if (openAI) {
                sidePanelStateLogic.actions.openSidePanel(
                    SidePanelTab.Max,
                    autoRunMaxPrompt(
                        `Help me build my product analytics Home dashboard (dashboard ID ${result.id}). Ask me what I want to track, then add relevant insights to this dashboard.`
                    )
                )
            }
        },
    })),
    listeners(({ actions, values }) => {
        let templateCreationInFlight = false

        return {
            createDashboardFromTemplate: async ({
                template,
                variables,
                redirectAfterCreation = true,
                creationContext = null,
            }) => {
                if (templateCreationInFlight) {
                    return
                }
                templateCreationInFlight = true
                actions.setIsLoading(true)
                const setAsHomeTabDashboard = values.setAsHomeTabDashboardAfterCreation
                actions.setAsHomeTabDashboardAfterCreation(false)
                const tiles = makeTilesUsingVariables(
                    isMetricTemplate(template) ? WEBSITE_METRICS_METRIC_CARD_TILES : template.tiles,
                    variables
                )
                const dashboardJSON = {
                    ...template,
                    tiles,
                }

                try {
                    actions.hideNewDashboardModal()
                    // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. dashboardsCreateFromTemplateJsonCreate() from 'products/dashboards/frontend/generated/api' serves this route, but its generated types do not describe this call yet, so fix the endpoint's OpenAPI schema first.
                    const result: DashboardType = await api.create(
                        `api/projects/${teamLogic.values.currentTeamId}/dashboards/create_from_template_json`,
                        {
                            template: dashboardJSON,
                            creation_context: creationContext,
                            _create_in_folder: UNFILED_DASHBOARDS_FOLDER,
                        }
                    )

                    actions.resetNewDashboard()
                    const queryBasedDashboard = getQueryBasedDashboard(result)
                    queryBasedDashboard && dashboardsModel.actions.addDashboardSuccess(queryBasedDashboard)
                    actions.submitNewDashboardSuccessWithResult(result, variables, setAsHomeTabDashboard)

                    posthog.capture('dashboard created from template', {
                        dashboard_id: result.id,
                        template_id: template.id,
                        template_name: template.template_name,
                        template_variable_count: variables.length,
                        template_scope: template.scope ?? null,
                    })

                    if (redirectAfterCreation) {
                        router.actions.push(urls.dashboard(result.id))
                    }
                } catch (e: any) {
                    if (!isBreakpoint(e)) {
                        const message = e.code && e.detail ? `${e.code}: ${e.detail}` : e
                        lemonToast.error(`Could not create dashboard: ${message}`)
                    }
                } finally {
                    templateCreationInFlight = false
                    actions.setIsLoading(false)
                }
            },
        }
    }),
    urlToAction(({ actions }) => ({
        '/dashboard': (_, _searchParams, hashParams) => {
            if ('newDashboard' in hashParams) {
                actions.showNewDashboardModal()
            }
        },
    })),
    actionToUrl({
        hideNewDashboardModal: () => {
            const hashParams = { ...router.values.hashParams }
            delete hashParams['newDashboard']
            return [router.values.location.pathname, router.values.searchParams, hashParams]
        },
        showNewDashboardModal: () => {
            const hashParams = { ...router.values.hashParams }
            hashParams['newDashboard'] = 'modal'
            return [router.values.location.pathname, router.values.searchParams, hashParams]
        },
    }),
])
