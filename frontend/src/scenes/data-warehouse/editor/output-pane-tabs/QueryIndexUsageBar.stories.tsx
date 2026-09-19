import type { Meta, StoryObj } from '@storybook/react'

import {
    PredicateIndexUsage,
    PredicateIndexVerdict,
    PredicateScope,
    UnprunedTableScan,
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

const UNPRUNED_SCANS: UnprunedTableScan[] = [
    {
        table_name: 'events',
        partition_key: 'toYYYYMM(timestamp)',
        message: 'No filter on events.timestamp, so this reads your full event history.',
        fix: 'Add WHERE timestamp > now() - INTERVAL 30 DAY to read a recent time range.',
        fix_action: {
            title: 'Add a time range',
            edits: [{ start: 26, end: 26, text: ' WHERE timestamp > now() - INTERVAL 30 DAY' }],
        },
        start: 21,
        end: 27,
    },
]

export const SomeFiltersScan: Story = {
    render: () => (
        <div className="max-w-3xl">
            <QueryIndexUsageBar predicates={PREDICATES} scans={[]} />
        </div>
    ),
}

export const EveryFilterIndexed: Story = {
    render: () => (
        <div className="max-w-3xl">
            <QueryIndexUsageBar predicates={[PREDICATES[0]]} scans={[]} />
        </div>
    ),
}

export const RefreshingAfterAnEdit: Story = {
    render: () => (
        <div className="max-w-3xl">
            <QueryIndexUsageBar predicates={PREDICATES} scans={[]} refreshing />
        </div>
    ),
}

export const EveryFilterIndexedButNoTimeRange: Story = {
    render: () => (
        <div className="max-w-3xl">
            <QueryIndexUsageBar predicates={[PREDICATES[0]]} scans={UNPRUNED_SCANS} onApplyFix={() => {}} />
        </div>
    ),
}

export const NoTimeRangeAndNoFilters: Story = {
    render: () => (
        <div className="max-w-3xl">
            <QueryIndexUsageBar predicates={[]} scans={UNPRUNED_SCANS} onApplyFix={() => {}} />
        </div>
    ),
}
