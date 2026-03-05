import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getDefaultEventName, getProjectEventExistence } from 'lib/utils/getAppContext'
import { PathExpansion } from 'scenes/funnels/FunnelFlowGraph/pathFlowUtils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

import { eventNameToEventsNode } from '~/queries/nodes/InsightQuery/utils/eventNameToEventsNode'
import { EventsNode, FunnelsQuery, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { FunnelPathType, FunnelVizType, InsightLogicProps } from '~/types'

import type { journeyBuilderLogicType } from './journeyBuilderLogicType'

export const JOURNEY_BUILDER_INSIGHT_PROPS: InsightLogicProps = {
    dashboardItemId: 'new-AdHoc.InsightViz.journey-builder',
    dataNodeCollectionId: 'InsightViz.journey-builder',
}

function createDefaultQuery(): InsightVizNode<FunnelsQuery> {
    const defaultEvent = getDefaultEventName()
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.FunnelsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    name: defaultEvent === null ? 'All events' : defaultEvent,
                    event: defaultEvent,
                },
            ],
            funnelsFilter: {
                funnelVizType: FunnelVizType.Flow,
            },
        },
        full: true,
        showFilters: true,
    }
}

export const journeyBuilderLogic = kea<journeyBuilderLogicType>([
    path(['products', 'customer_analytics', 'frontend', 'components', 'CustomerJourneys', 'journeyBuilderLogic']),

    connect(() => ({
        actions: [insightDataLogic(JOURNEY_BUILDER_INSIGHT_PROPS), ['setQuery as setInsightQuery']],
        values: [featureFlagLogic, ['featureFlags']],
    })),

    actions({
        openBuilder: true,
        closeBuilder: true,
        setQuery: (query: InsightVizNode<FunnelsQuery>) => ({ query }),
        addStep: (insertAtIndex: number) => ({ insertAtIndex }),
        removeStep: (stepIndex: number) => ({ stepIndex }),
        updateStepEvent: (stepIndex: number, event: string | null, name: string) => ({
            stepIndex,
            event,
            name,
        }),
        addStepFromPath: (eventName: string, expansion: PathExpansion, funnelStepCount: number) => ({
            eventName,
            expansion,
            funnelStepCount,
        }),
        saveJourney: (name: string) => ({ name }),
        saveJourneySuccess: true,
        saveJourneyFailure: (error: string) => ({ error }),
    }),

    reducers({
        isBuilderOpen: [
            false,
            {
                openBuilder: () => true,
                closeBuilder: () => false,
            },
        ],
        query: [
            createDefaultQuery(),
            {
                setQuery: (_, { query }) => query,
                closeBuilder: () => createDefaultQuery(),
            },
        ],
        isSaving: [
            false,
            {
                saveJourney: () => true,
                saveJourneySuccess: () => false,
                saveJourneyFailure: () => false,
            },
        ],
    }),

    selectors({
        stepCount: [(s) => [s.query], (query): number => query.source.series.length],
        series: [(s) => [s.query], (query): EventsNode[] => query.source.series as EventsNode[]],
        taxonomicGroupTypes: [
            (s) => [s.featureFlags],
            (featureFlags): TaxonomicFilterGroupType[] => {
                const { hasPageview, hasScreen } = getProjectEventExistence()
                const supportsDwhFunnels = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_FUNNEL_DWH_SUPPORT]
                return [
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                    ...(hasPageview ? [TaxonomicFilterGroupType.PageviewEvents] : []),
                    ...(hasScreen ? [TaxonomicFilterGroupType.ScreenEvents] : []),
                    TaxonomicFilterGroupType.AutocaptureEvents,
                    ...(supportsDwhFunnels ? [TaxonomicFilterGroupType.DataWarehouse] : []),
                ]
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        setQuery: () => {
            actions.setInsightQuery(values.query)
        },

        openBuilder: () => {
            actions.setInsightQuery(values.query)
        },

        addStep: ({ insertAtIndex }) => {
            const series = [...values.query.source.series]
            const newStep: EventsNode = {
                kind: NodeKind.EventsNode,
                event: null as unknown as string,
                name: 'Select an event',
            }
            series.splice(insertAtIndex, 0, newStep)
            actions.setQuery({
                ...values.query,
                source: { ...values.query.source, series },
            })
        },

        removeStep: ({ stepIndex }) => {
            const series = values.query.source.series.filter((_, i) => i !== stepIndex)
            if (series.length === 0) {
                return
            }
            actions.setQuery({
                ...values.query,
                source: { ...values.query.source, series },
            })
        },

        updateStepEvent: ({ stepIndex, event, name }) => {
            const series = [...values.query.source.series]
            series[stepIndex] = {
                ...series[stepIndex],
                kind: NodeKind.EventsNode,
                event,
                name,
            } as EventsNode
            actions.setQuery({
                ...values.query,
                source: { ...values.query.source, series },
            })
        },

        addStepFromPath: ({ eventName, expansion, funnelStepCount }) => {
            let insertionIndex: number
            if (expansion.pathType === FunnelPathType.between) {
                insertionIndex = expansion.stepIndex
            } else if (expansion.pathType === FunnelPathType.before && expansion.stepIndex === 0) {
                insertionIndex = 0
            } else if (expansion.pathType === FunnelPathType.after) {
                insertionIndex = funnelStepCount
            } else {
                insertionIndex = 0
            }

            const newStep = eventNameToEventsNode(eventName)
            const series = [...values.query.source.series]
            series.splice(insertionIndex, 0, newStep)
            actions.setQuery({
                ...values.query,
                source: { ...values.query.source, series },
            })
        },

        saveJourney: async ({ name }) => {
            // Will be implemented in Step 10
        },
    })),
])
