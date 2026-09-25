import type { Meta, StoryObj } from '@storybook/react'

import {
    CostPlanStep,
    CostPlanStepKind,
    PredicateIndexUsage,
    PredicateIndexVerdict,
    PredicateScope,
    ScanEstimate,
    ScanEstimatePrecision,
    ScanEstimateSource,
    ScanEstimateTimeRange,
} from '~/queries/schema/schema-general'

import { QueryIndexUsageBar } from './QueryIndexUsageBar'

const meta: Meta<typeof QueryIndexUsageBar> = {
    title: 'Scenes-App/Data Warehouse/Query index usage',
    component: QueryIndexUsageBar,
}
export default meta

type Story = StoryObj<typeof QueryIndexUsageBar>

const PREDICATES: PredicateIndexUsage[] = [
    {
        property_name: '$browser',
        scope: PredicateScope.Event,
        operator: '==',
        source_label: 'materialized column',
        column_name: 'mat_$browser',
        semantic_type: 'String',
        physical_type: 'String',
        usable_indexes: ['bloom_filter'],
        verdict: PredicateIndexVerdict.Indexed,
        message: "Event property '$browser' uses its bloom filter index, so this filter skips rows that cannot match.",
    },
    {
        property_name: 'duration',
        scope: PredicateScope.Event,
        operator: '>',
        source_label: 'materialized column',
        column_name: 'mat_duration',
        semantic_type: 'Float',
        physical_type: 'String',
        usable_indexes: [],
        verdict: PredicateIndexVerdict.Blocked,
        message:
            "Event property 'duration' is stored as String but compared as Float, so every row is converted before the filter runs and the index on 'duration' cannot skip any data.",
        fix: "If 'duration' is not really Float, correct its type in data management. Otherwise add a filter that can skip data, such as a date range on timestamp.",
    },
    {
        property_name: 'plan_tier',
        scope: PredicateScope.Person,
        operator: '==',
        source_label: 'JSON blob',
        column_name: 'person_properties',
        semantic_type: 'String',
        physical_type: 'String',
        usable_indexes: [],
        verdict: PredicateIndexVerdict.UnindexedJson,
        message:
            "Person property 'plan_tier' is read out of the properties JSON on every row, with no index to skip data.",
        fix: "Materialize 'plan_tier' so this filter reads a dedicated column instead of parsing the JSON.",
    },
    {
        property_name: '$current_url',
        scope: PredicateScope.Event,
        operator: '!=',
        source_label: 'materialized column',
        column_name: 'mat_$current_url',
        semantic_type: 'String',
        physical_type: 'String',
        usable_indexes: [],
        verdict: PredicateIndexVerdict.OperatorNotIndexable,
        message:
            "Event property '$current_url' is filtered with '!=', which reads every row because no index can rule one out.",
    },
]

export const SomeFiltersScan: Story = {
    render: () => (
        <div className="max-w-3xl">
            <QueryIndexUsageBar predicates={PREDICATES} />
        </div>
    ),
}

export const EveryFilterIndexed: Story = {
    render: () => (
        <div className="max-w-3xl">
            <QueryIndexUsageBar predicates={[PREDICATES[0]]} />
        </div>
    ),
}

export const RefreshingAfterAnEdit: Story = {
    render: () => (
        <div className="max-w-3xl">
            <QueryIndexUsageBar predicates={PREDICATES} refreshing />
        </div>
    ),
}

const SMALL_SCAN: ScanEstimate = {
    rows: 42_000_000,
    upper_bound: false,
    tables: [
        {
            name: 'events',
            source: ScanEstimateSource.Events,
            precision: ScanEstimatePrecision.Measured,
            rows: 42_000_000,
            days: 30,
            events: ['$pageview'],
            time_range: ScanEstimateTimeRange.Bounded,
        },
    ],
}
const LARGE_OPEN_SCAN: ScanEstimate = {
    rows: 2_100_000_000,
    upper_bound: true,
    tables: [
        {
            name: 'events',
            source: ScanEstimateSource.Events,
            precision: ScanEstimatePrecision.Measured,
            rows: 2_100_000_000,
            days: 365,
            events: [],
            time_range: ScanEstimateTimeRange.Open,
        },
    ],
}
const MULTI_TABLE_SCAN: ScanEstimate = {
    rows: 42_200_000,
    upper_bound: true,
    tables: [
        {
            name: 'events',
            source: ScanEstimateSource.Events,
            precision: ScanEstimatePrecision.Measured,
            rows: 41_000_000,
            days: 30,
            events: ['$pageview'],
            time_range: ScanEstimateTimeRange.Bounded,
        },
        {
            name: 'stripe_charges',
            source: ScanEstimateSource.Warehouse,
            precision: ScanEstimatePrecision.SizeOnly,
            rows: 1_200_000,
            bytes: 356_515_840,
        },
        { name: 'persons', source: ScanEstimateSource.Clickhouse, precision: ScanEstimatePrecision.Unknown },
    ],
}

export const ScanEstimateWithFilters: Story = {
    render: () => (
        <div className="max-w-3xl">
            <QueryIndexUsageBar predicates={PREDICATES} estimate={SMALL_SCAN} />
        </div>
    ),
}

export const LargeScanWithoutFilters: Story = {
    render: () => (
        <div className="max-w-3xl">
            <QueryIndexUsageBar predicates={[]} estimate={LARGE_OPEN_SCAN} />
        </div>
    ),
}

export const MultipleTables: Story = {
    render: () => (
        <div className="max-w-3xl">
            <QueryIndexUsageBar predicates={[]} estimate={MULTI_TABLE_SCAN} />
        </div>
    ),
}

const COST_PLAN: CostPlanStep[] = [
    {
        kind: CostPlanStepKind.Scan,
        table: 'events',
        rows: 41_000_000,
        message: 'Scan events, about 41M rows (30 days)',
        detail: 'Events per day for the team, scaled to the timestamp range and narrowed to $pageview.',
    },
    {
        kind: CostPlanStepKind.Filter,
        table: 'events',
        message: 'Filter $browser = … reads every row',
        detail: "Event property '$browser' is read out of the properties JSON on every row, with no index to skip data.",
        fix: "Materialize '$browser' so this filter reads a dedicated column instead of parsing the JSON.",
    },
    {
        kind: CostPlanStepKind.Filter,
        table: 'events',
        message: 'Filter plan = … skips almost nothing',
        detail: "Event property 'plan' has a bloom filter index that covers this comparison. How much data it skips depends on how the values are spread across the table.",
    },
    {
        kind: CostPlanStepKind.Scan,
        table: 'stripe_charges',
        rows: 1_200_000,
        message: 'Scan stripe_charges, up to 1.2M rows, 340.0 MB on disk',
        detail: 'The whole table as it was last measured. How much of it the query reads is not estimated.',
    },
    {
        kind: CostPlanStepKind.Join,
        message: 'Join 2 tables. Rows after the join are not estimated.',
        detail: 'The estimate sums what each side reads. How many rows survive the join depends on the keys, which the planner does not model yet.',
    },
]

export const CostPlan: Story = {
    render: () => (
        <div className="max-w-3xl">
            <QueryIndexUsageBar predicates={PREDICATES.slice(0, 2)} estimate={MULTI_TABLE_SCAN} plan={COST_PLAN} />
        </div>
    ),
}
