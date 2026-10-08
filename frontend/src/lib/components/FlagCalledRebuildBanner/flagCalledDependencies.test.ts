import {
    actionOnlyReadsFlagCalls,
    actionReadsFlagCalls,
    cohortFlagCalledReferences,
    dependsOnFlagCalls,
    experimentFlagCalledReferences,
    insightFlagCalledReferences,
} from 'lib/components/FlagCalledRebuildBanner/flagCalledDependencies'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'

import {
    ActionsNode,
    DataTableNode,
    DataVisualizationNode,
    DataWarehouseNode,
    EventsNode,
    ExperimentTrendsQuery,
    FunnelExclusion,
    FunnelsQuery,
    GroupNode,
    InsightQueryNode,
    InsightVizNode,
    Node,
    NodeKind,
    RetentionQuery,
    TrendsQuery,
    TrendsQuerySeriesNode,
} from '~/queries/schema/schema-general'
import {
    ActionType,
    AnyCohortCriteriaType,
    BehavioralEventType,
    CohortCriteriaGroupFilter,
    CohortType,
    Experiment,
    FilterLogicalOperator,
    RetentionEntity,
    TimeUnitType,
} from '~/types'

const FLAG_CALLED = '$feature_flag_called'
const ACTION_ID = 5

// The two actions share an id, so a case can swap one for the other and change only the steps.
const FLAG_CALLED_ACTION = { id: ACTION_ID, steps: [{ event: FLAG_CALLED }] } as ActionType
const PAGEVIEW_ACTION = { id: ACTION_ID, steps: [{ event: '$pageview' }] } as ActionType

const events = (event: string | null): EventsNode => ({ kind: NodeKind.EventsNode, event })
const action = (id: number): ActionsNode => ({ kind: NodeKind.ActionsNode, id })
const trends = (series: TrendsQuerySeriesNode[]): TrendsQuery => ({ kind: NodeKind.TrendsQuery, series })
const viz = <T extends InsightQueryNode>(source: T): InsightVizNode<T> => ({ kind: NodeKind.InsightVizNode, source })

const funnelExcluding = (exclusion: FunnelExclusion): InsightVizNode<FunnelsQuery> =>
    viz({
        kind: NodeKind.FunnelsQuery,
        series: [events('$pageview'), events('signed_up')],
        funnelsFilter: { exclusions: [exclusion] },
    })

const retention = (targetEntity: RetentionEntity, returningEntity: RetentionEntity): InsightVizNode<RetentionQuery> =>
    viz({ kind: NodeKind.RetentionQuery, retentionFilter: { targetEntity, returningEntity } })

const FLAG_CALLED_ENTITY: RetentionEntity = { id: FLAG_CALLED, type: 'events' }
const PAGEVIEW_ENTITY: RetentionEntity = { id: '$pageview', type: 'events' }

const groupOf = (nodes: GroupNode['nodes']): GroupNode => ({
    kind: NodeKind.GroupNode,
    operator: FilterLogicalOperator.Or,
    nodes,
})

// The insights picker from #112991 builds this series to chart flag calls from flag_evaluations.
const FLAG_EVALUATIONS_SERIES: DataWarehouseNode = {
    kind: NodeKind.DataWarehouseNode,
    id: 'posthog.flag_evaluations',
    table_name: 'posthog.flag_evaluations',
    name: 'Feature flag called',
    timestamp_field: 'timestamp',
    id_field: 'uuid',
    distinct_id_field: 'distinct_id',
}

const SQL_INSIGHT: DataVisualizationNode = {
    kind: NodeKind.DataVisualizationNode,
    source: { kind: NodeKind.HogQLQuery, query: `SELECT count() FROM events WHERE event = '${FLAG_CALLED}'` },
}

const EVENTS_LIST: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: { kind: NodeKind.EventsQuery, select: ['*'], event: FLAG_CALLED },
}

const performed = (key: string | number, eventType: TaxonomicFilterGroupType): AnyCohortCriteriaType => ({
    type: BehavioralFilterKey.Behavioral,
    value: BehavioralEventType.PerformEvent,
    // The editor stores an action's numeric id in `key`, though the type says string.
    key: key as string,
    event_type: eventType,
    time_value: 30,
    time_interval: TimeUnitType.Day,
})

const followedBy = (seqEvent: string | number, seqEventType: TaxonomicFilterGroupType): AnyCohortCriteriaType => ({
    type: BehavioralFilterKey.Behavioral,
    value: BehavioralEventType.PerformSequenceEvents,
    key: '$pageview',
    event_type: TaxonomicFilterGroupType.Events,
    time_value: 30,
    time_interval: TimeUnitType.Day,
    seq_event: seqEvent,
    seq_event_type: seqEventType,
    seq_time_value: 15,
    seq_time_interval: TimeUnitType.Day,
})

const and = (values: AnyCohortCriteriaType[] | CohortCriteriaGroupFilter[]): CohortCriteriaGroupFilter => ({
    type: FilterLogicalOperator.And,
    values,
})

const dynamicCohort = (...groups: CohortCriteriaGroupFilter[]): CohortType => ({
    id: 1,
    is_static: false,
    groups: [],
    filters: { properties: { type: FilterLogicalOperator.Or, values: groups } },
})

// No code under test reads the clock. The start dates sit on both sides of the September 1 cutoff.
// They show that the predicate trusts the event the server resolved and does not apply the cutoff again.
const runningExperiment = (overrides: Partial<Experiment> = {}): Experiment =>
    ({
        id: 1,
        feature_flag_key: 'checkout-flow',
        start_date: '2026-09-15T00:00:00Z',
        end_date: null,
        archived: false,
        resolved_exposure_event: FLAG_CALLED,
        exposure_criteria: {},
        metrics: [],
        metrics_secondary: [],
        ...overrides,
    }) as Experiment

const legacyTrendsMetric = (exposureQuery?: TrendsQuery): ExperimentTrendsQuery => ({
    kind: NodeKind.ExperimentTrendsQuery,
    count_query: trends([events('$pageview')]),
    ...(exposureQuery ? { exposure_query: exposureQuery } : {}),
})

// The legacy trends runner ignores the resolved event, so these cases resolve to
// $experiment_exposure to leave the metric as the only path to $feature_flag_called.
const legacyExperiment = (exposureQuery?: TrendsQuery): Experiment =>
    runningExperiment({
        resolved_exposure_event: '$experiment_exposure',
        metrics: [legacyTrendsMetric(exposureQuery)],
    })

describe('flag called dependencies', () => {
    describe('insights', () => {
        it.each<[string, boolean, Node | null, ActionType[]]>([
            // Event nodes match on `event`.
            ['an events series on $feature_flag_called', true, viz(trends([events(FLAG_CALLED)])), []],
            [
                '$feature_flag_called inside a series group',
                true,
                viz(trends([groupOf([events('$pageview'), events(FLAG_CALLED)])])),
                [],
            ],
            [
                'a funnel exclusion on $feature_flag_called',
                true,
                funnelExcluding({ ...events(FLAG_CALLED), funnelFromStep: 0, funnelToStep: 1 }),
                [],
            ],
            // Retention entities name their event in `id`.
            ['a retention target on $feature_flag_called', true, retention(FLAG_CALLED_ENTITY, PAGEVIEW_ENTITY), []],
            [
                'a retention returning entity on $feature_flag_called',
                true,
                retention(PAGEVIEW_ENTITY, FLAG_CALLED_ENTITY),
                [],
            ],
            // Action references resolve through the action's steps.
            [
                'an action series with a $feature_flag_called step',
                true,
                viz(trends([action(ACTION_ID)])),
                [FLAG_CALLED_ACTION],
            ],
            [
                'a funnel exclusion on an action with a $feature_flag_called step',
                true,
                funnelExcluding({ ...action(ACTION_ID), funnelFromStep: 0, funnelToStep: 1 }),
                [FLAG_CALLED_ACTION],
            ],
            [
                'a retention target on an action with a $feature_flag_called step',
                true,
                retention({ id: ACTION_ID, type: 'actions' }, PAGEVIEW_ENTITY),
                [FLAG_CALLED_ACTION],
            ],
            [
                'an action series without a $feature_flag_called step',
                false,
                viz(trends([action(ACTION_ID)])),
                [PAGEVIEW_ACTION],
            ],
            // The banner renders nothing until the referenced actions load.
            ['an action series whose action has not loaded', false, viz(trends([action(ACTION_ID)])), []],
            // The rebuilt series shows the event's label as its name, so a match on `name` flags the fixed insight.
            ['the flag_evaluations series that replaces it', false, viz(trends([FLAG_EVALUATIONS_SERIES])), []],
            // An all-events series loses the flag calls from its counts, but the announcement covers it.
            ['an all-events series', false, viz(trends([events(null)])), []],
            ['a series on another event', false, viz(trends([events('$pageview')])), []],
            // A legacy insight saved with only `filters` arrives with a null query.
            ['no query', false, null, []],
            // Saved SQL insights get their own warning.
            ['a SQL query on $feature_flag_called', false, SQL_INSIGHT, []],
            // The events query runner already reads saved events lists from flag_evaluations.
            ['an events list filtered to $feature_flag_called', false, EVENTS_LIST, []],
        ])('an insight with %s depends on flag calls: %s', (_label, expected, query, actions) => {
            expect(dependsOnFlagCalls(insightFlagCalledReferences(query), actions)).toBe(expected)
        })
    })

    describe('cohorts', () => {
        it.each<[string, boolean, CohortType, ActionType[]]>([
            // Behavioral criteria name an event in `key`. A sequence names its second event in `seq_event`.
            [
                'a performed-event criterion on $feature_flag_called',
                true,
                dynamicCohort(and([performed(FLAG_CALLED, TaxonomicFilterGroupType.Events)])),
                [],
            ],
            [
                'a sequence followed by $feature_flag_called',
                true,
                dynamicCohort(and([followedBy(FLAG_CALLED, TaxonomicFilterGroupType.Events)])),
                [],
            ],
            // The API accepts groups nested deeper than the editor builds them.
            [
                'a $feature_flag_called criterion in a nested group after another group',
                true,
                dynamicCohort(
                    and([performed('$pageview', TaxonomicFilterGroupType.Events)]),
                    and([and([performed(FLAG_CALLED, TaxonomicFilterGroupType.Events)])])
                ),
                [],
            ],
            // Action criteria store the action id. The id resolves through the action's steps.
            [
                'an action criterion with a $feature_flag_called step',
                true,
                dynamicCohort(and([performed(ACTION_ID, TaxonomicFilterGroupType.Actions)])),
                [FLAG_CALLED_ACTION],
            ],
            [
                'a sequence followed by an action with a $feature_flag_called step',
                true,
                dynamicCohort(and([followedBy(ACTION_ID, TaxonomicFilterGroupType.Actions)])),
                [FLAG_CALLED_ACTION],
            ],
            [
                'an action criterion without a $feature_flag_called step',
                false,
                dynamicCohort(and([performed(ACTION_ID, TaxonomicFilterGroupType.Actions)])),
                [PAGEVIEW_ACTION],
            ],
            [
                'criteria on other events only',
                false,
                dynamicCohort(
                    and([
                        performed('$pageview', TaxonomicFilterGroupType.Events),
                        followedBy('signed_up', TaxonomicFilterGroupType.Events),
                    ])
                ),
                [],
            ],
            // A static cohort is a snapshot, so it never adds people from new flag calls.
            [
                'static membership and a $feature_flag_called criterion',
                false,
                {
                    ...dynamicCohort(and([performed(FLAG_CALLED, TaxonomicFilterGroupType.Events)])),
                    is_static: true,
                },
                [],
            ],
            // An experiment's exposure cohort counts the event on purpose. The experiment's banner covers it.
            [
                'experiment exposure management and a $feature_flag_called criterion',
                false,
                {
                    ...dynamicCohort(and([performed(FLAG_CALLED, TaxonomicFilterGroupType.Events)])),
                    experiment_set: [7],
                },
                [],
            ],
        ])('a cohort with %s depends on flag calls: %s', (_label, expected, cohort, actions) => {
            expect(dependsOnFlagCalls(cohortFlagCalledReferences(cohort), actions)).toBe(expected)
        })
    })

    describe('experiments', () => {
        it.each<[string, boolean, Experiment, ActionType[]]>([
            // A running experiment counts exposures on the event the server resolved.
            ['running on a resolved $feature_flag_called', true, runningExperiment(), []],
            [
                'running on an action exposure with a $feature_flag_called step',
                true,
                runningExperiment({
                    resolved_exposure_event: '$experiment_exposure',
                    exposure_criteria: { exposure_config: action(ACTION_ID) },
                }),
                [FLAG_CALLED_ACTION],
            ],
            [
                'running on a resolved $experiment_exposure',
                false,
                runningExperiment({
                    start_date: '2026-08-15T00:00:00Z',
                    resolved_exposure_event: '$experiment_exposure',
                }),
                [],
            ],
            [
                'running on a custom exposure event',
                false,
                runningExperiment({
                    exposure_criteria: {
                        exposure_config: {
                            kind: NodeKind.ExperimentEventExposureConfig,
                            event: '$pageview',
                            properties: [],
                        },
                    },
                }),
                [],
            ],
            // A legacy trends metric counts $feature_flag_called unless its exposure query names another event.
            ['with a legacy trends metric and no exposure query', true, legacyExperiment(), []],
            [
                'with a legacy trends metric whose exposure query is on $feature_flag_called',
                true,
                legacyExperiment(trends([events(FLAG_CALLED)])),
                [],
            ],
            [
                'with a legacy trends metric whose exposure query is on another event',
                false,
                legacyExperiment(trends([events('$pageview')])),
                [],
            ],
            // Only a running experiment still counts new exposures.
            ['still in draft', false, runningExperiment({ start_date: null }), []],
            ['that has ended', false, runningExperiment({ end_date: '2026-09-30T00:00:00Z' }), []],
            ['that is archived', false, runningExperiment({ archived: true }), []],
        ])('an experiment %s depends on flag calls: %s', (_label, expected, experiment, actions) => {
            expect(dependsOnFlagCalls(experimentFlagCalledReferences(experiment), actions)).toBe(expected)
        })
    })

    describe('actions', () => {
        it.each<[string, boolean, boolean, ActionType]>([
            [
                'a $feature_flag_called step after another step',
                true,
                false,
                { id: ACTION_ID, steps: [{ event: '$pageview' }, { event: FLAG_CALLED }] } as ActionType,
            ],
            [
                'only $feature_flag_called steps',
                true,
                true,
                { id: ACTION_ID, steps: [{ event: FLAG_CALLED }, { event: FLAG_CALLED }] } as ActionType,
            ],
            ['steps on other events only', false, false, PAGEVIEW_ACTION],
        ])(
            'an action with %s reads flag calls: %s, only flag calls: %s',
            (_label, readsFlagCalls, onlyFlagCalls, actionWithSteps) => {
                expect(actionReadsFlagCalls(actionWithSteps)).toBe(readsFlagCalls)
                expect(actionOnlyReadsFlagCalls(actionWithSteps)).toBe(onlyFlagCalls)
            }
        )
    })
})
