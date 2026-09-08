import type { Meta, StoryObj } from '@storybook/react'
import type { ComponentProps } from 'react'

import {
    PredicateFixAction,
    PredicateIndexUsage,
    PredicateIndexVerdict,
    PredicateScope,
} from '~/queries/schema/schema-general'

import { QueryIndexUsageFixActions } from './QueryIndexUsageFixActions'

// These render inside a table row that the index usage bar keeps collapsed, so a story on the bar
// never reaches them.
const meta: Meta<typeof QueryIndexUsageFixActions> = {
    title: 'Scenes-App/Data Warehouse/Query index usage fix actions',
    component: QueryIndexUsageFixActions,
    parameters: {
        testOptions: {
            viewportWidths: ['narrow', 'wide'],
        },
    },
}
export default meta

type Story = StoryObj<typeof QueryIndexUsageFixActions>

const BLOCKED: PredicateIndexUsage = {
    property_name: '$browser_version',
    scope: PredicateScope.Event,
    operator: '==',
    source_label: 'materialized column',
    semantic_type: 'String',
    physical_type: 'String',
    usable_indexes: [],
    verdict: PredicateIndexVerdict.Blocked,
    message: "Event property '$browser_version' is compared against a value of another type.",
    fix: "Write the value as text: '120'.",
    fix_action: PredicateFixAction.EditQuery,
    ai_fix_prompt: "Rewrite this filter so '$browser_version' is compared against a String value.",
    quickfix: { start: 58, end: 61, text: "'120'" },
}

const noop = (): void => {}

type RowProps = Omit<ComponentProps<typeof QueryIndexUsageFixActions>, 'onApplyQuickfix' | 'onFixWithAI'>

function Row({ predicate, ...rest }: RowProps): JSX.Element {
    return (
        <div className="flex flex-col gap-1 px-2 py-1 text-xs max-w-2xl">
            <p className="mb-0">{predicate.message}</p>
            {predicate.fix && <p className="mb-0 font-semibold">{predicate.fix}</p>}
            <QueryIndexUsageFixActions predicate={predicate} onApplyQuickfix={noop} onFixWithAI={noop} {...rest} />
        </div>
    )
}

export const ReplaceALiteral: Story = { render: () => <Row predicate={BLOCKED} /> }

// A long IN list: the label names the action rather than repeating a replacement that would widen
// the row until the table scrolls sideways.
export const ReplaceALongList: Story = {
    render: () => (
        <Row
            predicate={{
                ...BLOCKED,
                operator: 'in',
                fix: "Write the values as text: ('1', '2', '3', '4', '5', '6', '7', '8').",
                quickfix: { start: 40, end: 64, text: "('1', '2', '3', '4', '5', '6', '7', '8')" },
            }}
        />
    ),
}

// No quickfix, because a float's text form is not the text a row stores.
export const FixWithAi: Story = {
    render: () => (
        <Row predicate={{ ...BLOCKED, fix: "Compare '$browser_version' against text.", quickfix: undefined }} />
    ),
}

export const FixWithAiInFlight: Story = {
    render: () => (
        <Row
            predicate={{ ...BLOCKED, fix: "Compare '$browser_version' against text.", quickfix: undefined }}
            fixWithAILoading
        />
    ),
}

export const ReportStillCatchingUp: Story = { render: () => <Row predicate={BLOCKED} stale /> }

export const EditPropertyType: Story = {
    render: () => (
        <Row
            predicate={{
                ...BLOCKED,
                property_name: 'duration',
                operator: '>',
                semantic_type: 'Float',
                message: "Event property 'duration' is stored as String but compared as Float.",
                fix: "If 'duration' does not really hold a number, correct its type in data management.",
                fix_action: PredicateFixAction.EditPropertyType,
                ai_fix_prompt: undefined,
                quickfix: undefined,
            }}
        />
    ),
}

export const MaterializeTheProperty: Story = {
    render: () => (
        <Row
            predicate={{
                ...BLOCKED,
                property_name: 'plan_tier',
                scope: PredicateScope.Person,
                source_label: 'JSON blob',
                verdict: PredicateIndexVerdict.UnindexedJson,
                message: "Person property 'plan_tier' is read out of the properties JSON on every row.",
                fix: "Materialize 'plan_tier' so this filter reads a dedicated column instead of parsing the JSON.",
                fix_action: PredicateFixAction.Materialize,
                ai_fix_prompt: undefined,
                quickfix: undefined,
            }}
        />
    ),
}
