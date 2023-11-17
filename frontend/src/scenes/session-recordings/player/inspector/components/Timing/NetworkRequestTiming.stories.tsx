import { mswDecorator } from '~/mocks/browser'
import { Meta } from '@storybook/react'
import { PerformanceEvent } from '~/types'
import { NetworkRequestTiming } from 'scenes/session-recordings/player/inspector/components/Timing/NetworkRequestTiming'

const meta: Meta<typeof NetworkRequestTiming> = {
    title: 'Components/NetworkRequestTiming',
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
                    connect_end: 9525.599999964237,
                    connect_start: 9525.599999964237,
                    decoded_body_size: 18260,
                    domain_lookup_end: 9525.599999964237,
                    domain_lookup_start: 9525.599999964237,
                    duration: 935.5,
                    encoded_body_size: 18260,
                    entry_type: 'resource',
                    fetch_start: 9525.599999964237,
                    initiator_type: 'fetch',
                    name: 'http://localhost:8000/api/organizations/@current/plugins/repository/',
                    next_hop_protocol: 'http/1.1',
                    redirect_end: 0,
                    redirect_start: 0,
                    render_blocking_status: 'non-blocking',
                    request_start: 9803.099999964237,
                    response_end: 10461.099999964237,
                    response_start: 10428.399999976158,
                    response_status: 200,
                    secure_connection_start: 0,
                    start_time: 9525.599999964237,
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
