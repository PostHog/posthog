import { Meta } from '@storybook/react'

import { NetworkRequestTiming } from 'scenes/session-recordings/player/inspector/components/Timing/NetworkRequestTiming'

import { mswDecorator } from '~/mocks/browser'
import { PerformanceEvent } from '~/types'

const meta: Meta<typeof NetworkRequestTiming> = {
    title: 'Components/NetworkRequest/Timing',
    component: NetworkRequestTiming,
    decorators: [
        mswDecorator({
            get: {},
        }),
    ],
}
export default meta

export function Basic(): JSX.Element {
    return (
        <NetworkRequestTiming
            performanceEvent={
                {
                    // fake an event with every step visible
                    start_time: 10,
                    redirect_start: 10,
                    redirect_end: 20,
                    fetch_start: 20,
                    domain_lookup_start: 30,
                    domain_lookup_end: 40,
                    connect_start: 40,
                    secure_connection_start: 45,
                    connect_end: 50,
                    request_start: 60,
                    response_start: 70,
                    response_end: 80,
                    load_event_end: 90,
                    duration: 90,

                    decoded_body_size: 18260,
                    encoded_body_size: 18260,
                    entry_type: 'resource',
                    initiator_type: 'fetch',
                    name: 'http://localhost:8000/api/organizations/@current/plugins/repository/',
                    next_hop_protocol: 'http/1.1',
                    render_blocking_status: 'non-blocking',
                    response_status: 200,
                    time_origin: '1699990397357',
                    timestamp: 1699990406882,
                    transfer_size: 18560,
                    window_id: '018bcf51-b1f0-7fe0-ac05-10543621f4f2',
                    worker_start: 0,
                    uuid: '12345',
                    distinct_id: '23456',
                    session_id: 'abcde',
                    pageview_id: 'fghij',
                    current_url: 'http://localhost:8000/insights',
                } satisfies PerformanceEvent
            }
        />
    )
}
