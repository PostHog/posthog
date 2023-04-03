import {
    kea,
    props,
    key,
    path,
    selectors,
    listeners,
    connect,
    BreakPointFunction,
    reducers,
    actions,
    defaults,
} from 'kea'
import {
    CorrelationConfigType,
    FunnelCorrelation,
    FunnelCorrelationResultsType,
    FunnelCorrelationType,
    FunnelsFilterType,
    InsightLogicProps,
} from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { visibilitySensorLogic } from 'lib/components/VisibilitySensor/visibilitySensorLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { funnelLogic } from './funnelLogic'
import api from 'lib/api'

import type { funnelCorrelationLogicType } from './funnelCorrelationLogicType'
import { loaders } from 'kea-loaders'
import { lemonToast } from '@posthog/lemon-ui'
import { teamLogic } from 'scenes/teamLogic'
import { funnelDataLogic } from './funnelDataLogic'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { insightLogic } from 'scenes/insights/insightLogic'

export const funnelCorrelationLogic = kea<funnelCorrelationLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('insight_funnel')),
    path((key) => ['scenes', 'funnels', 'funnelCorrelationLogic', key]),
    connect({
        values: [
            insightLogic,
            ['isUsingDataExploration'],
            funnelLogic,
            ['filters'],
            funnelDataLogic,
            ['querySource'],
            teamLogic,
            ['currentTeamId', 'currentTeam'],
        ],
        actions: [funnelLogic, ['loadResultsSuccess']],
        logic: [eventUsageLogic],
    }),
    actions({
        setCorrelationTypes: (types: FunnelCorrelationType[]) => ({ types }),
        excludeEventFromProject: (eventName: string) => ({ eventName }),
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
                    } catch (error) {
                        lemonToast.error('Failed to load correlation results', { toastId: 'funnel-correlation-error' })
                        return { events: [] }
                    }
                },
            },
        ],
    })),
    reducers({
        shouldReportCorrelationViewed: [
            true as boolean,
            {
                loadResultsSuccess: () => true,
                [eventUsageLogic.actionTypes.reportCorrelationViewed]: (current, { propertiesTable }) => {
                    if (!propertiesTable) {
                        return false // don't report correlation viewed again, since it was for events earlier
                    }
                    return current
                },
            },
        ],
        shouldReportPropertyCorrelationViewed: [
            true as boolean,
            {
                loadResultsSuccess: () => true,
                [eventUsageLogic.actionTypes.reportCorrelationViewed]: (current, { propertiesTable }) => {
                    if (propertiesTable) {
                        return false
                    }
                    return current
                },
            },
        ],
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
    }),
    selectors({
        apiParams: [
            (s) => [s.isUsingDataExploration, s.dataExplorationApiParams, s.legacyApiParams],
            (isUsingDataExploration, dataExplorationApiParams, legacyApiParams) => {
                return isUsingDataExploration ? dataExplorationApiParams : legacyApiParams
            },
        ],
        dataExplorationApiParams: [
            (s) => [s.querySource],
            (querySource) => {
                const cleanedParams: Partial<FunnelsFilterType> = querySource
                    ? cleanFilters(queryNodeToFilter(querySource))
                    : {}
                return cleanedParams
            },
        ],
        legacyApiParams: [
            (s) => [s.filters],
            (filters) => {
                const cleanedParams: Partial<FunnelsFilterType> = cleanFilters(filters)
                return cleanedParams
            },
        ],

        correlationPropKey: [
            () => [(_, props) => props],
            (props): string => `correlation-${keyForInsightLogicProps('insight_funnel')(props)}`,
        ],
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
    }),
    listeners(({ values }) => ({
        [visibilitySensorLogic({ id: values.correlationPropKey }).actionTypes.setVisible]: async (
            { visible }: { visible: boolean },
            breakpoint: BreakPointFunction
        ) => {
            if (visible && values.shouldReportCorrelationViewed) {
                eventUsageLogic.actions.reportCorrelationViewed(values.filters, 0)
                await breakpoint(10000)
                eventUsageLogic.actions.reportCorrelationViewed(values.filters, 10)
            }
        },

        [visibilitySensorLogic({ id: `${values.correlationPropKey}-properties` }).actionTypes.setVisible]: async (
            { visible }: { visible: boolean },
            breakpoint: BreakPointFunction
        ) => {
            if (visible && values.shouldReportPropertyCorrelationViewed) {
                eventUsageLogic.actions.reportCorrelationViewed(values.filters, 0, true)
                await breakpoint(10000)
                eventUsageLogic.actions.reportCorrelationViewed(values.filters, 10, true)
            }
        },

        setCorrelationTypes: ({ types }) => {
            eventUsageLogic.actions.reportCorrelationInteraction(
                FunnelCorrelationResultsType.Events,
                'set correlation types',
                { types }
            )
        },

        excludeEventFromProject: async ({ eventName }) => {
            appendToCorrelationConfig('excluded_event_names', values.excludedEventNames, eventName)

            eventUsageLogic.actions.reportCorrelationInteraction(FunnelCorrelationResultsType.Events, 'exclude event', {
                event_name: eventName,
            })
        },
    })),
])

export const appendToCorrelationConfig = (
    configKey: keyof CorrelationConfigType,
    currentValue: string[],
    configValue: string
): void => {
    // Helper to handle updating correlationConfig within the Team model. Only
    // handles further appending to current values.

    // When we exclude a property, we want to update the config stored
    // on the current Team/Project.
    const oldCurrentTeam = teamLogic.values.currentTeam

    // If we haven't actually retrieved the current team, we can't
    // update the config.
    if (oldCurrentTeam === null || !currentValue) {
        console.warn('Attempt to update correlation config without first retrieving existing config')
        return
    }

    const oldCorrelationConfig = oldCurrentTeam.correlation_config

    const configList = [...Array.from(new Set(currentValue.concat([configValue])))]

    const correlationConfig = {
        ...oldCorrelationConfig,
        [configKey]: configList,
    }

    teamLogic.actions.updateCurrentTeam({
        correlation_config: correlationConfig,
    })
}
