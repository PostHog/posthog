import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { groupPropertiesModel } from '~/models/groupPropertiesModel'
import { FunnelCorrelation, FunnelCorrelationResultsType, FunnelCorrelationType, InsightLogicProps } from '~/types'

import { teamLogic } from '../teamLogic'
import { funnelCorrelationLogic } from './funnelCorrelationLogic'
import type { funnelPropertyCorrelationLogicType } from './funnelPropertyCorrelationLogicType'
import { appendToCorrelationConfig } from './funnelUtils'

// List of events that should be excluded, if we don't have an explicit list of
// excluded properties. Copied from
// https://github.com/PostHog/posthog/issues/6474#issuecomment-952044722
export const DEFAULT_EXCLUDED_PERSON_PROPERTIES = [
    '$initial_geoip_postal_code',
    '$initial_geoip_latitude',
    '$initial_geoip_longitude',
    '$geoip_latitude',
    '$geoip_longitude',
    '$geoip_postal_code',
    '$geoip_continent_code',
    '$geoip_continent_name',
    '$initial_geoip_continent_code',
    '$initial_geoip_continent_name',
    '$geoip_time_zone',
    '$geoip_country_code',
    '$geoip_subdivision_1_code',
    '$initial_geoip_subdivision_1_code',
    '$geoip_subdivision_2_code',
    '$initial_geoip_subdivision_2_code',
    '$geoip_subdivision_name',
    '$initial_geoip_subdivision_name',
]

export const funnelPropertyCorrelationLogic = kea<funnelPropertyCorrelationLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('insight_funnel')),
    path((key) => ['scenes', 'funnels', 'funnelPropertyCorrelationLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            funnelCorrelationLogic(props),
            ['apiParams', 'aggregationGroupTypeIndex'],
            teamLogic,
            ['currentTeamId', 'currentTeam'],
            groupPropertiesModel,
            ['groupProperties'],
        ],
    })),
    actions({
        setPropertyCorrelationTypes: (types: FunnelCorrelationType[]) => ({ types }),
        setPropertyNames: (propertyNames: string[]) => ({ propertyNames }),
        excludePropertyFromProject: (propertyName: string) => ({ propertyName }),
        setAllProperties: true,
    }),
    defaults({
        // This is a hack to get `FunnelCorrelationResultsType` imported in `funnelCorrelationLogicType.ts`
        __ignore: null as FunnelCorrelationResultsType | null,
    }),
    loaders(({ values }) => ({
        propertyCorrelations: [
            { events: [] } as Record<'events', FunnelCorrelation[]>,
            {
                loadPropertyCorrelations: async (_, breakpoint) => {
                    const targetProperties = values.propertyNames

                    if (targetProperties.length === 0) {
                        return { events: [] }
                    }

                    await breakpoint(100)

                    try {
                        const results: Omit<FunnelCorrelation, 'result_type'>[] = (
                            await api.create(`api/projects/${values.currentTeamId}/insights/funnel/correlation`, {
                                ...values.apiParams,
                                funnel_correlation_type: 'properties',
                                funnel_correlation_names: targetProperties,
                                funnel_correlation_exclude_names: values.excludedPropertyNames,
                            })
                        ).result?.events

                        return {
                            events: results.map((result) => ({
                                ...result,
                                result_type: FunnelCorrelationResultsType.Properties,
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
        propertyCorrelationTypes: [
            [FunnelCorrelationType.Success, FunnelCorrelationType.Failure] as FunnelCorrelationType[],
            {
                setPropertyCorrelationTypes: (_, { types }) => types,
            },
        ],
        propertyNames: [
            [] as string[],
            {
                setPropertyNames: (_, { propertyNames }) => propertyNames,
                setAllProperties: () => ['$all'],
                excludePropertyFromProject: (selectedProperties, { propertyName }) => {
                    return selectedProperties.filter((p) => p !== propertyName)
                },
            },
        ],
        loadedPropertyCorrelationsTableOnce: [
            false,
            {
                loadPropertyCorrelations: () => true,
            },
        ],
    }),
    selectors({
        propertyCorrelationValues: [
            (s) => [s.propertyCorrelations, s.propertyCorrelationTypes, s.excludedPropertyNames],
            (propertyCorrelations, propertyCorrelationTypes, excludedPropertyNames): FunnelCorrelation[] => {
                return propertyCorrelations.events
                    .filter(
                        (correlation) =>
                            propertyCorrelationTypes.includes(correlation.correlation_type) &&
                            !excludedPropertyNames.includes(correlation.event.event.split('::')[0])
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
        excludedPropertyNames: [
            (s) => [s.currentTeam],
            (currentTeam): string[] =>
                currentTeam?.correlation_config?.excluded_person_property_names || DEFAULT_EXCLUDED_PERSON_PROPERTIES,
        ],
        isPropertyExcludedFromProject: [
            (s) => [s.excludedPropertyNames],
            (excludedPropertyNames) => (propertyName: string) =>
                excludedPropertyNames.find((name) => name === propertyName) !== undefined,
        ],
    }),
    listeners(({ actions, values }) => ({
        excludePropertyFromProject: ({ propertyName }) => {
            appendToCorrelationConfig('excluded_person_property_names', values.excludedPropertyNames, propertyName)
        },
        setPropertyNames: async () => {
            actions.loadPropertyCorrelations({})
        },
        setAllProperties: async () => {
            actions.loadPropertyCorrelations({})
        },
    })),
])
