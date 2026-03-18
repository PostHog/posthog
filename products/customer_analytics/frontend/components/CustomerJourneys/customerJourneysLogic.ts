import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { LemonSelectOptions } from 'lib/lemon-ui/LemonSelect/LemonSelect'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { isUUIDLike } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { FunnelsQuery, InsightVizNode } from '~/queries/schema/schema-general'
import { isInsightVizNode } from '~/queries/utils'
import { insightsApi } from '~/scenes/insights/utils/api'
import { FunnelVizType, PropertyFilterType, PropertyOperator, QueryBasedInsightModel } from '~/types'

import { CustomerJourneyApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import type { customerJourneysLogicType } from './customerJourneysLogicType'

export interface CustomerJourneysLogicProps {
    key?: string
    personId?: string
    groupKey?: string
    groupTypeIndex?: number
}

export const customerJourneysLogic = kea<customerJourneysLogicType>([
    path(['products', 'customer_analytics', 'frontend', 'components', 'CustomerJourneys', 'customerJourneysLogic']),
    props({} as CustomerJourneysLogicProps),
    key((props) => props.key ?? 'default'),
    connect(() => ({
        actions: [eventUsageLogic, ['reportCustomerJourneyViewed']],
    })),
    actions({
        setActiveJourneyId: (journeyId: string | null) => ({ journeyId }),
        selectFirstJourneyIfNeeded: (journeys: CustomerJourneyApi[]) => ({ journeys }),
    }),
    lazyLoaders(({ values }) => ({
        journeys: {
            __default: [] as CustomerJourneyApi[],
            loadJourneys: async (): Promise<CustomerJourneyApi[]> => {
                const response = await api.customerJourneys.list()
                return response.results
            },
            addJourney: async ({
                insightId,
                name,
                description,
            }: {
                insightId: number
                name: string
                description?: string
            }): Promise<CustomerJourneyApi[]> => {
                await api.customerJourneys.create({ insight: insightId, name, description })
                const response = await api.customerJourneys.list()
                return response.results
            },
            updateJourney: async ({
                journeyId,
                name,
                description,
            }: {
                journeyId: string
                name: string
                description?: string
            }): Promise<CustomerJourneyApi[]> => {
                await api.customerJourneys.update(journeyId, { name, description })
                const response = await api.customerJourneys.list()
                return response.results
            },
            deleteJourney: async (journeyId: string): Promise<CustomerJourneyApi[]> => {
                await api.customerJourneys.delete(journeyId)
                return values.journeys.filter((j) => j.id !== journeyId)
            },
        },
        activeInsight: {
            __default: null as QueryBasedInsightModel | null,
            loadActiveInsight: async () => {
                const journey = values.activeJourney
                if (!journey) {
                    return null
                }
                return await insightsApi.getByNumericId(journey.insight)
            },
        },
    })),
    reducers({
        activeJourneyId: [
            null as string | null,
            {
                setActiveJourneyId: (_, { journeyId }) => journeyId,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        loadJourneysSuccess: ({ journeys }) => {
            actions.selectFirstJourneyIfNeeded(journeys)
        },
        addJourneySuccess: ({ journeys }) => {
            lemonToast.success('Customer journey created')
            actions.selectFirstJourneyIfNeeded(journeys)
        },
        addJourneyFailure: ({ error }) => {
            posthog.captureException(error)
            lemonToast.error(error || 'Failed to create customer journey')
        },
        updateJourneySuccess: ({ journeys }) => {
            lemonToast.success('Customer journey updated')
            actions.selectFirstJourneyIfNeeded(journeys)
        },
        updateJourneyFailure: ({ error }) => {
            posthog.captureException(error)
            lemonToast.error(error || 'Failed to update customer journey')
        },
        deleteJourneySuccess: ({ journeys }) => {
            lemonToast.success('Customer journey deleted')
            actions.selectFirstJourneyIfNeeded(journeys)
        },
        deleteJourneyFailure: ({ error }) => {
            posthog.captureException(error)
            lemonToast.error('Failed to delete customer journey')
        },
        selectFirstJourneyIfNeeded: ({ journeys }) => {
            if (journeys.length > 0) {
                const currentActive = values.activeJourneyId
                const stillExists = currentActive && journeys.some((j: CustomerJourneyApi) => j.id === currentActive)
                if (!stillExists) {
                    actions.setActiveJourneyId(journeys[0].id)
                }
            } else {
                actions.setActiveJourneyId(null)
            }
        },
        setActiveJourneyId: () => {
            actions.loadActiveInsight()
        },
        loadActiveInsightSuccess: () => {
            const journey = values.activeJourney
            const insight = values.activeInsight
            if (journey && insight) {
                const stepCount =
                    (insight.query as InsightVizNode<FunnelsQuery> | undefined)?.source?.series?.length ?? 0
                actions.reportCustomerJourneyViewed(journey.id, journey.name, stepCount)
            }
        },
    })),
    selectors({
        journeyOptions: [
            (s) => [s.journeys],
            (journeys): LemonSelectOptions<string> =>
                journeys.map((journey) => ({
                    value: journey.id,
                    label: journey.name,
                })),
        ],
        activeJourney: [
            (s) => [s.journeys, s.activeJourneyId],
            (journeys, activeId): CustomerJourneyApi | null => {
                if (!activeId) {
                    return null
                }
                return journeys.find((j) => j.id === activeId) || null
            },
        ],
        activeJourneyFullQuery: [
            (s) => [s.activeInsight],
            (activeInsight): InsightVizNode<FunnelsQuery> | null => {
                const query = activeInsight?.query
                if (!query || !isInsightVizNode(query)) {
                    return null
                }
                const source = query.source as FunnelsQuery
                return {
                    ...query,
                    full: true,
                    source: {
                        ...source,
                        funnelsFilter: {
                            ...source.funnelsFilter,
                            funnelVizType: FunnelVizType.Flow,
                        },
                    },
                } as InsightVizNode<FunnelsQuery>
            },
        ],
        isProfileMode: [
            () => [(_, p) => p.personId, (_, p) => p.groupKey],
            (personId: string | undefined, groupKey: string | undefined): boolean => !!personId || !!groupKey,
        ],
        filteredQuery: [
            (s) => [
                s.activeJourneyFullQuery,
                s.isProfileMode,
                (_, p) => p.personId,
                (_, p) => p.groupKey,
                (_, p) => p.groupTypeIndex,
            ],
            (query, isProfileMode, personId, groupKey, groupTypeIndex): InsightVizNode<FunnelsQuery> | null => {
                if (!query || !isProfileMode) {
                    return query
                }
                if (personId && !isUUIDLike(personId)) {
                    return query
                }
                const entityFilter = personId
                    ? { type: PropertyFilterType.HogQL, key: `person_id = '${personId}'` }
                    : {
                          type: PropertyFilterType.Event,
                          key: `$group_${groupTypeIndex}`,
                          value: [String(groupKey)],
                          operator: PropertyOperator.Exact,
                      }
                return {
                    ...query,
                    full: false,
                    embedded: true,
                    source: {
                        ...query.source,
                        properties: [
                            ...(Array.isArray(query.source.properties) ? query.source.properties : []),
                            entityFilter,
                        ],
                    },
                } as InsightVizNode<FunnelsQuery>
            },
        ],
    }),
])
