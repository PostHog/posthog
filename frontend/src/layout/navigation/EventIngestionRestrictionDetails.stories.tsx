import { Meta, StoryObj } from '@storybook/react'

import { EventIngestionRestriction, RestrictionType } from 'lib/logic/eventIngestionRestrictionLogic'

import { EventIngestionRestrictionDetails } from './EventIngestionRestrictionDetails'

function restriction(overrides: Partial<EventIngestionRestriction>): EventIngestionRestriction {
    return {
        restriction_type: RestrictionType.DROP_EVENT_FROM_INGESTION,
        distinct_ids: [],
        session_ids: [],
        event_names: [],
        event_uuids: [],
        pipelines: ['analytics'],
        ...overrides,
    }
}

const meta: Meta<typeof EventIngestionRestrictionDetails> = {
    title: 'Layout/Navigation/EventIngestionRestrictionDetails',
    component: EventIngestionRestrictionDetails,
    tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof EventIngestionRestrictionDetails>

export const WholeProject: Story = {
    args: {
        restrictions: [restriction({})],
    },
}

export const ScopedToDistinctIds: Story = {
    args: {
        restrictions: [
            restriction({
                restriction_type: RestrictionType.SKIP_PERSON_PROCESSING,
                distinct_ids: ['user-1', 'user-2', 'anonymous-3f2a'],
            }),
            restriction({
                restriction_type: RestrictionType.FORCE_OVERFLOW_FROM_INGESTION,
                distinct_ids: ['user-1'],
                event_names: ['$pageview'],
                pipelines: ['analytics', 'session_recordings'],
            }),
        ],
    },
}

export const ManyDistinctIds: Story = {
    args: {
        restrictions: [restriction({ distinct_ids: Array.from({ length: 30 }, (_, i) => `user-${i + 1}`) })],
    },
}
