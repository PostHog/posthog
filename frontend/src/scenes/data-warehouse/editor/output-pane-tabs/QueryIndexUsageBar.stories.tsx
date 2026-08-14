import type { Meta, StoryObj } from '@storybook/react'

import { PredicateIndexUsage, PredicateIndexVerdict } from '~/queries/schema/schema-general'

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
        scope: 'event',
        operator: '==',
        source_label: 'materialized column',
        column_name: 'mat_$browser',
        semantic_type: 'String',
        physical_type: 'String',
        usable_indexes: ['bloom_filter'],
        verdict: PredicateIndexVerdict.Indexed,
        message: "Event property '$browser' filters on column 'mat_$browser' using its bloom filter index.",
    },
    {
        property_name: 'duration',
        scope: 'event',
        operator: '>',
        source_label: 'materialized column',
        column_name: 'mat_duration',
        semantic_type: 'Float',
        physical_type: 'String',
        usable_indexes: [],
        verdict: PredicateIndexVerdict.Blocked,
        message:
            "Event property 'duration' is stored as String but its type is set to Float. Every row has to be converted, so the index on 'mat_duration' goes unused.",
        fix: "Materialize 'duration' as Float, or set its type to String to match how it is stored.",
    },
    {
        property_name: 'plan_tier',
        scope: 'person',
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
        scope: 'event',
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
