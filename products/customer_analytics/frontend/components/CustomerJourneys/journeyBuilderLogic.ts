import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getDefaultEventName, getProjectEventExistence } from 'lib/utils/getAppContext'
import { PathExpansion } from 'scenes/funnels/FunnelFlowGraph/pathFlowUtils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

import { eventNameToEventsNode } from '~/queries/nodes/InsightQuery/utils/eventNameToEventsNode'
import {
    ActionsNode,
    AnyEntityNode,
    DataWarehouseNode,
    EventsNode,
    FunnelsQuery,
    InsightVizNode,
    NodeKind,
} from '~/queries/schema/schema-general'
import { insightsApi } from '~/scenes/insights/utils/api'
import { FunnelPathType, FunnelVizType, InsightLogicProps } from '~/types'

import { customerJourneysLogic } from './customerJourneysLogic'
import type { journeyBuilderLogicType } from './journeyBuilderLogicType'

const JOURNEY_NAME_MAX_LENGTH = 64
const INSIGHT_NAME_PREFIX = 'Journey: '
export const JOURNEY_NAME_INPUT_MAX_LENGTH = JOURNEY_NAME_MAX_LENGTH - INSIGHT_NAME_PREFIX.length

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
        actions: [
            insightDataLogic(JOURNEY_BUILDER_INSIGHT_PROPS),
            ['setQuery as setInsightQuery'],
            customerJourneysLogic,
            ['addJourney', 'addJourneySuccess', 'addJourneyFailure'],
        ],
        values: [featureFlagLogic, ['featureFlags']],
    })),

    actions({
        openBuilder: true,
        closeBuilder: true,
        setQuery: (query: InsightVizNode<FunnelsQuery>) => ({ query }),
        setQueryFromViz: (query: InsightVizNode<FunnelsQuery>) => ({ query }),
        addStep: (insertAtIndex: number) => ({ insertAtIndex }),
        removeStep: (stepIndex: number) => ({ stepIndex }),
        updateStepEvent: (
            stepIndex: number,
            value: string | null,
            groupType: TaxonomicFilterGroupType,
            item: Record<string, any>
        ) => ({
            stepIndex,
            value,
            groupType,
            item,
        }),
        addStepFromPath: (eventName: string, expansion: PathExpansion, funnelStepCount: number) => ({
            eventName,
            expansion,
            funnelStepCount,
        }),
        setJourneyName: (name: string) => ({ name }),
        saveJourney: true,
        saveJourneyFailure: (error: string) => ({ error }),
    }),

    reducers({
        isBuilderOpen: [
            false,
            {
                openBuilder: () => true,
                addJourneySuccess: () => false,
            },
        ],
        query: [
            createDefaultQuery(),
            {
                setQuery: (_, { query }) => query,
                setQueryFromViz: (_, { query }) => query,
                addJourneySuccess: () => createDefaultQuery(),
            },
        ],
        journeyName: [
            '',
            {
                setJourneyName: (_, { name }) => name,
                addJourneySuccess: () => '',
            },
        ],
        isSaving: [
            false,
            {
                saveJourney: () => true,
                addJourneySuccess: () => false,
                addJourneyFailure: () => false,
                saveJourneyFailure: () => false,
            },
        ],
    }),

    selectors({
        stepCount: [(s) => [s.query], (query): number => query.source.series.length],
        series: [(s) => [s.query], (query): AnyEntityNode[] => query.source.series as AnyEntityNode[]],
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
            const defaultEvent = getDefaultEventName()
            const newStep: EventsNode = {
                kind: NodeKind.EventsNode,
                event: defaultEvent,
                name: defaultEvent === null ? 'All events' : defaultEvent,
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

        updateStepEvent: ({ stepIndex, value, groupType, item }) => {
            const series = [...values.query.source.series]
            const name = item?.name || value || ''

            let node: AnyEntityNode
            if (groupType === TaxonomicFilterGroupType.Actions) {
                node = {
                    kind: NodeKind.ActionsNode,
                    id: parseInt(String(value), 10),
                    name,
                } as ActionsNode
            } else if (groupType === TaxonomicFilterGroupType.DataWarehouse) {
                node = {
                    kind: NodeKind.DataWarehouseNode,
                    id: String(value),
                    table_name: item?.name || String(value),
                    id_field: item?.id_field || 'id',
                    timestamp_field: item?.timestamp_field || 'timestamp',
                    distinct_id_field: item?.distinct_id_field || 'distinct_id',
                    name,
                } as DataWarehouseNode
            } else {
                node = {
                    kind: NodeKind.EventsNode,
                    event: value,
                    name,
                } as EventsNode
            }

            series[stepIndex] = node
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

        saveJourney: async () => {
            const { series, journeyName, query } = values
            const name = (journeyName.trim() || 'Untitled journey').slice(0, JOURNEY_NAME_MAX_LENGTH)
            const insightName = `${INSIGHT_NAME_PREFIX}${name}`.slice(0, JOURNEY_NAME_MAX_LENGTH)

            const hasEmptySteps = series.some((s) => {
                if (s.kind === NodeKind.EventsNode) {
                    return s.event === null
                }
                if (s.kind === NodeKind.ActionsNode) {
                    return !s.id
                }
                if (s.kind === NodeKind.DataWarehouseNode) {
                    return !s.table_name
                }
                return false
            })
            if (hasEmptySteps) {
                lemonToast.warning('Select an event for all steps before saving')
                actions.saveJourneyFailure('Empty steps')
                return
            }

            try {
                const insight = await insightsApi.create({
                    query,
                    name: insightName,
                    saved: true,
                })

                // Delegate journey creation + list reload to customerJourneysLogic
                // addJourney creates the record, reloads the list, and addJourneySuccess selects it
                actions.addJourney({
                    insightId: insight.id,
                    name,
                })

                actions.closeBuilder()
            } catch (e) {
                const message = e instanceof Error ? e.message : 'Failed to save journey'
                actions.saveJourneyFailure(message)
                lemonToast.error(message)
            }
        },
    })),
])
