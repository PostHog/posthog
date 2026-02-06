import FuseClass from 'fuse.js'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { projectLogic } from 'scenes/projectLogic'
import { userLogic } from 'scenes/userLogic'

import { deleteFromTree, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { CyclotronJobFiltersType, HogFunctionType, HogFunctionTypeType, UserType } from '~/types'

import { getDestinationTypeFromTemplateId } from '../configuration/hogFunctionConfigurationLogic'
import type { hogFunctionsListLogicType } from './hogFunctionsListLogicType'

const ERROR_TRACKING_TEMPLATE_IDS = [
    'error-tracking-issue-created',
    'error-tracking-issue-reopened',
    'error-tracking-issue-spiking',
] as const

const TRIGGER_EVENT_MAP: Record<string, string> = {
    'error-tracking-issue-created': '$error_tracking_issue_created',
    'error-tracking-issue-reopened': '$error_tracking_issue_reopened',
    'error-tracking-issue-spiking': '$error_tracking_issue_spiking',
}

function isErrorTrackingAlert(hogFunction: HogFunctionType): boolean {
    const templateId = hogFunction.template?.id
    return templateId ? ERROR_TRACKING_TEMPLATE_IDS.includes(templateId as any) : false
}

export const CDP_TEST_HIDDEN_FLAG = '[CDP-TEST-HIDDEN]'
// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<HogFunctionType> {}

export type HogFunctionListFilters = {
    search?: string
    showPaused?: boolean
    createdBy?: string | null
}

export type HogFunctionListLogicProps = {
    logicKey?: string
    type: HogFunctionTypeType
    additionalTypes?: HogFunctionTypeType[]
    forceFilterGroups?: CyclotronJobFiltersType[]
    syncFiltersWithUrl?: boolean
    manualFunctions?: HogFunctionType[]
}

export const shouldShowHogFunction = (hogFunction: HogFunctionType, user?: UserType | null): boolean => {
    if (!user) {
        return false
    }
    if (hogFunction.name.includes(CDP_TEST_HIDDEN_FLAG) && !user.is_impersonated && !user.is_staff) {
        return false
    }
    return true
}

export const hogFunctionsListLogic = kea<hogFunctionsListLogicType>([
    props({} as HogFunctionListLogicProps),
    key((props) =>
        JSON.stringify({
            ...props,
            manualFunctions: null, // We don't care about these
        })
    ),
    path((id) => ['scenes', 'pipeline', 'hogFunctionsListLogic', id]),
    connect(() => ({
        values: [
            projectLogic,
            ['currentProjectId'],
            userLogic,
            ['user', 'hasAvailableFeature'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    })),
    actions({
        toggleEnabled: (hogFunction: HogFunctionType, enabled: boolean) => ({ hogFunction, enabled }),
        deleteHogFunction: (hogFunction: HogFunctionType) => ({ hogFunction }),
        setFilters: (filters: Partial<HogFunctionListFilters>) => ({ filters }),
        resetFilters: true,
        addHogFunction: (hogFunction: HogFunctionType) => ({ hogFunction }),
        setReorderModalOpen: (open: boolean) => ({ open }),
        saveHogFunctionOrder: (newOrders: Record<string, number>) => ({ newOrders }),
    }),
    reducers(() => ({
        filters: [
            {} as HogFunctionListFilters,
            {
                setFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                }),
                resetFilters: () => ({}),
            },
        ],
        reorderModalOpen: [
            false as boolean,
            {
                setReorderModalOpen: (_, { open }) => open,
            },
        ],
    })),
    loaders(({ values, actions, props }) => ({
        hogFunctions: [
            [] as HogFunctionType[],
            {
                loadHogFunctions: async () => {
                    return (
                        await api.hogFunctions.list({
                            filter_groups: props.forceFilterGroups,
                            types: [props.type, ...(props.additionalTypes || [])],
                            // TODO: This is a temporary fix. We need proper server-side pagination
                            // once we rework the data pipelines UI and batch exports is no longer
                            // part of the same list
                            limit: 300,
                        })
                    ).results
                },
                saveHogFunctionOrder: async ({ newOrders }) => {
                    return await api.hogFunctions.rearrange(newOrders)
                },
                deleteHogFunction: async ({ hogFunction }) => {
                    await deleteWithUndo({
                        endpoint: `projects/${values.currentProjectId}/hog_functions`,
                        object: {
                            id: hogFunction.id,
                            name: hogFunction.name,
                        },
                        callback: (undo) => {
                            if (undo) {
                                actions.loadHogFunctions()
                                refreshTreeItem('hog_function/', hogFunction.id)
                            } else {
                                deleteFromTree('hog_function/', hogFunction.id)
                            }
                        },
                    })

                    return values.hogFunctions.filter((x) => x.id !== hogFunction.id)
                },
                toggleEnabled: async ({ hogFunction, enabled }) => {
                    const { hogFunctions } = values
                    const hogFunctionIndex = hogFunctions.findIndex((hf) => hf.id === hogFunction.id)
                    const response = await api.hogFunctions.update(hogFunction.id, {
                        enabled,
                    })
                    return [
                        ...hogFunctions.slice(0, hogFunctionIndex),
                        response,
                        ...hogFunctions.slice(hogFunctionIndex + 1),
                    ]
                },
                addHogFunction: ({ hogFunction }) => {
                    return [hogFunction, ...values.hogFunctions]
                },
            },
        ],
    })),
    selectors({
        loading: [(s) => [s.hogFunctionsLoading], (hogFunctionsLoading) => hogFunctionsLoading],
        sortedHogFunctions: [
            (s) => [s.hogFunctions, (_, props) => props.manualFunctions ?? []],
            (hogFunctions, manualFunctions): HogFunctionType[] => {
                const enabledFirst = [...hogFunctions, ...manualFunctions].sort(
                    (a, b) => Number(b.enabled) - Number(a.enabled)
                )
                return enabledFirst
            },
        ],
        enabledHogFunctions: [
            (s) => [s.sortedHogFunctions],
            (hogFunctions): HogFunctionType[] => {
                return hogFunctions.filter((hogFunction) => hogFunction.enabled)
            },
        ],
        hogFunctionsFuse: [
            (s) => [s.sortedHogFunctions],
            (hogFunctions): Fuse => {
                return new FuseClass(hogFunctions || [], {
                    keys: ['name', 'description'],
                    threshold: 0.3,
                })
            },
        ],

        filteredHogFunctions: [
            (s) => [s.filters, s.sortedHogFunctions, s.hogFunctionsFuse, s.user],
            (filters, hogFunctions, hogFunctionsFuse, user): HogFunctionType[] => {
                const { search, showPaused, createdBy } = filters

                return (search ? hogFunctionsFuse.search(search).map((x) => x.item) : hogFunctions).filter((x) => {
                    if (!shouldShowHogFunction(x, user)) {
                        return false
                    }

                    if (!showPaused && !x.enabled) {
                        return false
                    }

                    if (createdBy && x.created_by?.uuid !== createdBy) {
                        return false
                    }

                    return true
                })
            },
        ],

        hiddenHogFunctions: [
            (s) => [s.sortedHogFunctions, s.filteredHogFunctions],
            (sortedHogFunctions, filteredHogFunctions): HogFunctionType[] => {
                return sortedHogFunctions.filter((hogFunction) => !filteredHogFunctions.includes(hogFunction))
            },
        ],
    }),

    listeners(({ actions }) => ({
        saveHogFunctionOrderSuccess: () => {
            actions.setReorderModalOpen(false)
            lemonToast.success('Order updated successfully')
        },
        saveHogFunctionOrderFailure: () => {
            lemonToast.error('Failed to update order')
        },
        toggleEnabled: ({ hogFunction, enabled }) => {
            if (isErrorTrackingAlert(hogFunction)) {
                const templateId = hogFunction.template?.id
                posthog.capture('error_tracking_alert_toggled', {
                    alert_id: hogFunction.id,
                    trigger_event: templateId ? TRIGGER_EVENT_MAP[templateId] : null,
                    destination_type: getDestinationTypeFromTemplateId(templateId),
                    enabled,
                })
            }
        },
        deleteHogFunction: ({ hogFunction }) => {
            if (isErrorTrackingAlert(hogFunction)) {
                const templateId = hogFunction.template?.id
                const createdAt = hogFunction.created_at ? new Date(hogFunction.created_at) : null
                const timeSinceCreationDays = createdAt
                    ? Math.floor((Date.now() - createdAt.getTime()) / (1000 * 60 * 60 * 24))
                    : null

                posthog.capture('error_tracking_alert_deleted', {
                    alert_id: hogFunction.id,
                    trigger_event: templateId ? TRIGGER_EVENT_MAP[templateId] : null,
                    destination_type: getDestinationTypeFromTemplateId(templateId),
                    time_since_creation_days: timeSinceCreationDays,
                })
            }
        },
    })),

    actionToUrl(({ props, values }) => {
        if (!props.syncFiltersWithUrl) {
            return {}
        }
        const urlFromFilters = (): [
            string,
            Record<string, any>,
            Record<string, any>,
            {
                replace: boolean
            },
        ] => [
            router.values.location.pathname,

            values.filters,
            router.values.hashParams,
            {
                replace: true,
            },
        ]

        return {
            setFilters: () => urlFromFilters(),
            resetFilters: () => urlFromFilters(),
        }
    }),

    urlToAction(({ props, actions, values }) => ({
        '*': (_, searchParams) => {
            if (!props.syncFiltersWithUrl) {
                return
            }

            if (!objectsEqual(values.filters, searchParams)) {
                actions.setFilters(searchParams)
            }
        },
    })),
])
