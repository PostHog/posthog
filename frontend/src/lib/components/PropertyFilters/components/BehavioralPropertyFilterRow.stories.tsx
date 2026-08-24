import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import {
    BehavioralEventType,
    BehavioralPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
    TimeUnitType,
} from '~/types'

import { BehavioralPropertyFilterRow } from './BehavioralPropertyFilterRow'

type Story = StoryObj<typeof BehavioralPropertyFilterRow>
const meta: Meta<typeof BehavioralPropertyFilterRow> = {
    title: 'Filters/Behavioral Property Filter Row',
    component: BehavioralPropertyFilterRow,
    args: {
        editable: true,
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
