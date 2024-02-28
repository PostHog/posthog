import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { teamLogic } from 'scenes/teamLogic'

import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { FunnelCorrelationQuery, FunnelCorrelationType, FunnelsActorsQuery, NodeKind } from '~/queries/schema'
import { FunnelCorrelation, FunnelCorrelationResultsType, FunnelsFilterType, InsightLogicProps } from '~/types'

import type { funnelCorrelationLogicType } from './funnelCorrelationLogicType'
import { funnelDataLogic } from './funnelDataLogic'
import { appendToCorrelationConfig } from './funnelUtils'

export const funnelCorrelationLogic = kea<funnelCorrelationLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('insight_funnel')),
    path((key) => ['scenes', 'funnels', 'funnelCorrelationLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            funnelDataLogic(props),
            ['querySource', 'hogQLInsightsFunnelsFlagEnabled'],
            teamLogic,
            ['currentTeamId', 'currentTeam'],
        ],
    })),
    actions({
        setCorrelationTypes: (types: FunnelCorrelationType[]) => ({ types }),
        excludeEventFromProject: (eventName: string) => ({ eventName }),

        excludeEventPropertyFromProject: (eventName: string, propertyName: string) => ({ eventName, propertyName }),
        addNestedTableExpandedKey: (expandKey: string) => ({ expandKey }),
        removeNestedTableExpandedKey: (expandKey: string) => ({ expandKey }),
    }),
    defaults({
        // This is a hack to get `FunnelCorrelationResultsType` imported in `funnelCorrelationLogicType.ts`
        __ignore: null as FunnelCorrelationResultsType | null,
    }),
    loaders(({ values }) => ({
        correlations: [
            { events: [] } as Record<'events', FunnelCorrelation[]>,
            {
                loadEventCorrelations: async (_, breakpoint) => {
                    await breakpoint(100)

                    try {
                        if (values.hogQLInsightsFunnelsFlagEnabled) {
                            const actorsQuery: FunnelsActorsQuery = {
                                kind: NodeKind.InsightActorsQuery,
                                source: values.querySource!,
                            }

                            const query: FunnelCorrelationQuery = {
                                kind: NodeKind.FunnelCorrelationQuery,
                                source: actorsQuery,
                                correlationType: FunnelCorrelationType.Events,
                                funnelCorrelationExcludeEventNames: values.excludedEventNames,
                            }
                            const response = await api.query(query)
                            return {
                                events: response.results.events.map((result) => ({
                                    ...result,
                                    result_type: FunnelCorrelationResultsType.Events,
                                })) as FunnelCorrelation[],
                            }
                        } else {
                            const results: Omit<FunnelCorrelation, 'result_type'>[] = (
                                await api.create(`api/projects/${values.currentTeamId}/insights/funnel/correlation`, {
                                    ...values.apiParams,
                                    funnel_correlation_type: 'events',
                                    funnel_correlation_exclude_event_names: values.excludedEventNames,
                                })
                            ).result?.events

                            return {
                                events: results.map((result) => ({
                                    ...result,
                                    result_type: FunnelCorrelationResultsType.Events,
                                })),
                            }
                        }
                    } catch (error) {
                        lemonToast.error('Failed to load correlation results', { toastId: 'funnel-correlation-error' })
                        return { events: [] }
                    }
                },
            },
        ],
        eventWithPropertyCorrelations: [
            {} as Record<string, FunnelCorrelation[]>,
            {
                loadEventWithPropertyCorrelations: async (eventName: string) => {
                    const results: Omit<FunnelCorrelation, 'result_type'>[] = (
                        await api.create(`api/projects/${values.currentTeamId}/insights/funnel/correlation`, {
                            ...values.apiParams,
                            funnel_correlation_type: 'event_with_properties',
                            funnel_correlation_event_names: [eventName],
                            funnel_correlation_event_exclude_property_names: values.excludedEventPropertyNames,
                        })
                    ).result?.events

                    return {
                        [eventName]: results.map((result) => ({
                            ...result,
                            result_type: FunnelCorrelationResultsType.EventWithProperties,
                        })),
                    }
                },
            },
        ],
    })),
    reducers({
        correlationTypes: [
            [FunnelCorrelationType.Success, FunnelCorrelationType.Failure] as FunnelCorrelationType[],
            {
                setCorrelationTypes: (_, { types }) => types,
            },
        ],
        loadedEventCorrelationsTableOnce: [
            false,
            {
                loadEventCorrelations: () => true,
            },
        ],
        nestedTableExpandedKeys: [
            [] as string[],
            {
                removeNestedTableExpandedKey: (state, { expandKey }) => {
                    return state.filter((key) => key !== expandKey)
                },
                addNestedTableExpandedKey: (state, { expandKey }) => {
                    return [...state, expandKey]
                },
                loadEventCorrelationsSuccess: () => {
                    return []
                },
            },
        ],
        eventWithPropertyCorrelations: {
            loadEventCorrelationsSuccess: () => {
                return {}
            },
            loadEventWithPropertyCorrelationsSuccess: (state, { eventWithPropertyCorrelations }) => {
                return {
                    ...state,
                    ...eventWithPropertyCorrelations,
                }
            },
        },
    }),
    selectors({
        apiParams: [
            (s) => [s.querySource],
            (querySource) => {
                const cleanedParams: Partial<FunnelsFilterType> = querySource
                    ? cleanFilters(queryNodeToFilter(querySource))
                    : {}
                return cleanedParams
            },
        ],
        aggregationGroupTypeIndex: [(s) => [s.querySource], (querySource) => querySource?.aggregation_group_type_index],

        // event correlation
        correlationValues: [
            (s) => [s.correlations, s.correlationTypes, s.excludedEventNames],
            (correlations, correlationTypes, excludedEventNames): FunnelCorrelation[] => {
                return correlations.events
                    ?.filter(
                        (correlation) =>
                            correlationTypes.includes(correlation.correlation_type) &&
                            !excludedEventNames.includes(correlation.event.event)
                    )
                    .map((value) => {
                        return {
                            ...value,
                            odds_ratio:
                                value.correlation_type === FunnelCorrelationType.Success
                                    ? value.odds_ratio
                                    : 1 / value.odds_ratio,
                        }
                    })
                    .sort((first, second) => {
                        return second.odds_ratio - first.odds_ratio
                    })
            },
        ],
        excludedEventNames: [
            (s) => [s.currentTeam],
            (currentTeam): string[] => currentTeam?.correlation_config?.excluded_event_names || [],
        ],
        isEventExcluded: [
            (s) => [s.excludedEventNames],
            (excludedEventNames) => (eventName: string) =>
                excludedEventNames.find((name) => name === eventName) !== undefined,
        ],

        // event property correlation
        excludedEventPropertyNames: [
            (s) => [s.currentTeam],
            (currentTeam): string[] => currentTeam?.correlation_config?.excluded_event_property_names || [],
        ],
        isEventPropertyExcluded: [
            (s) => [s.excludedEventPropertyNames],
            (excludedEventPropertyNames) => (propertyName: string) =>
                excludedEventPropertyNames.find((name) => name === propertyName) !== undefined,
        ],
        eventWithPropertyCorrelationsValues: [
            (s) => [s.eventWithPropertyCorrelations, s.correlationTypes, s.excludedEventPropertyNames],
            (
                eventWithPropertyCorrelations,
                correlationTypes,
                excludedEventPropertyNames
            ): Record<string, FunnelCorrelation[]> => {
                const eventWithPropertyCorrelationsValues: Record<string, FunnelCorrelation[]> = {}
                for (const key in eventWithPropertyCorrelations) {
                    if (eventWithPropertyCorrelations.hasOwnProperty(key)) {
                        eventWithPropertyCorrelationsValues[key] = eventWithPropertyCorrelations[key]
                            ?.filter(
                                (correlation) =>
                                    correlationTypes.includes(correlation.correlation_type) &&
                                    !excludedEventPropertyNames.includes(correlation.event.event.split('::')[1])
                            )
                            .map((value) => {
                                return {
                                    ...value,
                                    odds_ratio:
                                        value.correlation_type === FunnelCorrelationType.Success
                                            ? value.odds_ratio
                                            : 1 / value.odds_ratio,
                                }
                            })
                            .sort((first, second) => {
                                return second.odds_ratio - first.odds_ratio
                            })
                    }
                }
                return eventWithPropertyCorrelationsValues
            },
        ],
        eventHasPropertyCorrelations: [
            (s) => [s.eventWithPropertyCorrelationsValues],
            (eventWithPropertyCorrelationsValues): ((eventName: string) => boolean) => {
                return (eventName) => {
                    return !!eventWithPropertyCorrelationsValues[eventName]
                }
            },
        ],
    }),
    listeners(({ values }) => ({
        excludeEventFromProject: async ({ eventName }) => {
            appendToCorrelationConfig('excluded_event_names', values.excludedEventNames, eventName)
        },
        excludeEventPropertyFromProject: async ({ propertyName }) => {
            appendToCorrelationConfig('excluded_event_property_names', values.excludedEventPropertyNames, propertyName)
        },
    })),
])
