import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { mswDecorator } from '~/mocks/browser'
import {
    BehavioralEventType,
    BehavioralPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
    TimeUnitType,
} from '~/types'

import { BehavioralPropertyFilterRow } from './BehavioralPropertyFilterRow'

const CHECKOUT_ACTION = { id: 42, name: 'Completed checkout' }

type Story = StoryObj<typeof BehavioralPropertyFilterRow>
const meta: Meta<typeof BehavioralPropertyFilterRow> = {
    title: 'Filters/Behavioral Property Filter Row',
    component: BehavioralPropertyFilterRow,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/actions/': { count: 1, next: null, previous: null, results: [CHECKOUT_ACTION] },
                '/api/event/values/': [],
            },
        }),
    ],
    args: {
        editable: true,
        pageKey: 'behavioral-row-story',
    },
    render: (props) => {
        const [filter, setFilter] = useState<BehavioralPropertyFilter>({
            type: PropertyFilterType.Behavioral,
            value: BehavioralEventType.PerformEvent,
            key: '$pageview',
            event_type: 'events',
            time_value: 30,
            time_interval: TimeUnitType.Day,
        })

        return <BehavioralPropertyFilterRow {...props} filter={filter} onChange={setFilter} />
    },
}
export default meta

export const Default: Story = {}

export const ReadOnly: Story = {
    args: { editable: false },
}

export const Action: Story = {
    render: (props) => (
        <BehavioralPropertyFilterRow
            {...props}
            filter={{
                type: PropertyFilterType.Behavioral,
                value: BehavioralEventType.PerformEvent,
                key: String(CHECKOUT_ACTION.id),
                event_type: 'actions',
                time_value: 30,
                time_interval: TimeUnitType.Day,
            }}
            onChange={() => {}}
        />
    ),
}

export const WithEventFilters: Story = {
    render: (props) => {
        const [filter, setFilter] = useState<BehavioralPropertyFilter>({
            type: PropertyFilterType.Behavioral,
            value: BehavioralEventType.PerformEvent,
            key: 'insight created',
            event_type: 'events',
            negation: true,
            time_value: 30,
            time_interval: TimeUnitType.Day,
            event_filters: [
                { type: PropertyFilterType.Event, key: 'source', operator: PropertyOperator.Exact, value: ['web'] },
                {
                    type: PropertyFilterType.Event,
                    key: '$browser',
                    operator: PropertyOperator.Exact,
                    value: ['Chrome'],
                },
            ],
        })

        return <BehavioralPropertyFilterRow {...props} filter={filter} onChange={setFilter} />
    },
}

export const ReadOnlyWithEventFilters: Story = {
    args: { editable: false },
    render: (props) => (
        <BehavioralPropertyFilterRow
            {...props}
            filter={{
                type: PropertyFilterType.Behavioral,
                value: BehavioralEventType.PerformEvent,
                key: 'insight created',
                event_type: 'events',
                negation: true,
                time_value: 30,
                time_interval: TimeUnitType.Day,
                event_filters: [
                    { type: PropertyFilterType.Event, key: 'source', operator: PropertyOperator.Exact, value: ['web'] },
                ],
            }}
            onChange={() => {}}
        />
    ),
}

export const ReadOnlyWithCount: Story = {
    args: { editable: false },
    render: (props) => (
        <BehavioralPropertyFilterRow
            {...props}
            filter={{
                type: PropertyFilterType.Behavioral,
                value: BehavioralEventType.PerformMultipleEvents,
                key: '$pageview',
                event_type: 'events',
                operator: PropertyOperator.GreaterThanOrEqual,
                operator_value: 3,
                time_value: 30,
                time_interval: TimeUnitType.Day,
            }}
            onChange={() => {}}
        />
    ),
}
