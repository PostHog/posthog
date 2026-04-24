import type { Meta, StoryObj } from '@storybook/react'
import { createRef } from 'react'

import { dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils'
import { PlayerSeekbarTicks } from 'scenes/session-recordings/player/controller/PlayerSeekbarTicks'
import { InspectorListItemEvent } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

import { mswDecorator } from '~/mocks/browser'
import { RecordingEventType } from '~/types'

const endTimeMs = 60_000

type PlayerSeekbarTicksStoryArgs = {
    seekbarItems: InspectorListItemEvent[]
}

type Story = StoryObj<PlayerSeekbarTicksStoryArgs>

const meta: Meta<PlayerSeekbarTicksStoryArgs> = {
    title: 'Components/PlayerController/PlayerSeekbarTicks',
    component: PlayerSeekbarTicks,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:project_id/event_definitions/promoted_properties/': { promoted_properties: {} },
            },
        }),
    ],
    parameters: {
        mockDate: '2025-09-23',
    },
}
export default meta

function makeEventTick(
    event: string,
    timeInRecording: number,
    properties: Record<string, any> = {}
): InspectorListItemEvent {
    const data: RecordingEventType = {
        elements: [],
        event,
        fullyLoaded: true,
        id: `evt-${uuid()}`,
        playerTime: timeInRecording,
        timestamp: dayjs('2025-11-04').add(timeInRecording, 'ms').toISOString(),
        properties,
    }
    return {
        data,
        search: '',
        timeInRecording,
        timestamp: dayjs('2025-11-04').add(timeInRecording, 'ms'),
        type: 'events',
        key: `key-${uuid()}`,
    }
}

const renderTicks = ({ seekbarItems }: PlayerSeekbarTicksStoryArgs): JSX.Element => {
    const hoverRef = createRef<HTMLDivElement>()
    return (
        <div className="relative h-8 w-full bg-surface-secondary" ref={hoverRef}>
            <PlayerSeekbarTicks
                seekbarItems={seekbarItems}
                endTimeMs={endTimeMs}
                seekToTime={() => undefined}
                hoverRef={hoverRef}
            />
        </div>
    )
}

export const Default: Story = {
    render: renderTicks,
    args: {
        seekbarItems: [
            makeEventTick('$pageview', 3_000, { $pathname: '/home', $current_url: 'https://my-site.io/home' }),
            makeEventTick('$pageview', 18_000, {
                $pathname: '/products',
                $current_url: 'https://my-site.io/products',
            }),
            makeEventTick('$autocapture', 32_000),
            makeEventTick('order_placed', 48_000, { order_id: 'ord_12345' }),
        ],
    },
}

export const WithPromotedPropertyOverride: Story = {
    render: renderTicks,
    args: {
        seekbarItems: [
            makeEventTick('order_placed', 12_000, {
                order_id: 'ord_42',
                customer_email: 'buyer@example.com',
                total_usd: 42.5,
            }),
            makeEventTick('$pageview', 35_000, {
                $pathname: '/checkout',
                $current_url: 'https://my-site.io/checkout',
            }),
        ],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:project_id/event_definitions/promoted_properties/': {
                    promoted_properties: { order_placed: 'order_id', $pageview: '$current_url' },
                },
            },
        }),
    ],
}
