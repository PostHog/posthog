import { PerfBlock } from 'scenes/performance/WebPerformanceWaterfallChart'
import { PerformanceEvent } from '~/types'
import { ComponentMeta, ComponentStory } from '@storybook/react'

export default {
    title: 'Components/Web Performance Waterfall Chart',
    component: PerfBlock,
    argTypes: {
        max: {
            defaultValue: 1000,
        },
    },
} as ComponentMeta<typeof PerfBlock>

const performanceEvent: PerformanceEvent = {
    uuid: '01859867-3e9b-0000-4737-5bf965b8adc5',
    session_id: '185986732a31357-0aec5fc7ba94ed-17525635-16a7f0-185986732a41bd0',
    window_id: '185986732a52166-0fe0d9e5005971-17525635-16a7f0-185986732a616',
    pageview_id: '185986732901048-0c017847f8688d-17525635-16a7f0-185986732912458',
    distinct_id: 'UBhyEPC6HQEHgTFOeHCzQCyTbjPn7MzXbcVa9TPizmx',
    current_url:
        'http://127.0.0.1:8000/recordings/recent?filters=%7B%22session_recording_duration%22%3A%7B%22type%22%3A%22recording%22%2C%22key%22%3A%22duration%22%2C%22value%22%3A60%2C%22operator%22%3A%22gt%22%7D%2C%22properties%22%3A%5B%5D%2C%22events%22%3A%5B%5D%2C%22actions%22%3A%5B%5D%2C%22date_from%22%3A%22-21d%22%7D#sessionRecordingId=1859781977b1ed8-0aac13c41bf94d-17525635-16a7f0-1859781977c2370',
    entry_type: 'navigation',
    time_origin: '2023-01-09T21:19:37.181000Z',
    timestamp: '2023-01-09T21:19:37.181000Z',
    name: 'http://127.0.0.1:8000/recordings/recent?filters=%7B%22session_recording_duration%22%3A%7B%22type%22%3A%22recording%22%2C%22key%22%3A%22duration%22%2C%22value%22%3A60%2C%22operator%22%3A%22gt%22%7D%2C%22properties%22%3A%5B%5D%2C%22events%22%3A%5B%5D%2C%22actions%22%3A%5B%5D%2C%22date_from%22%3A%22-21d%22%7D#sessionRecordingId=1859781977b1ed8-0aac13c41bf94d-17525635-16a7f0-1859781977c2370',
    start_time: 0,
    duration: 626.7999999970198,
    redirect_start: 0,
    redirect_end: 0,
    worker_start: 0,
    fetch_start: 3,
    domain_lookup_start: 3,
    domain_lookup_end: 3,
    connect_start: 3,
    secure_connection_start: 0,
    connect_end: 3,
    request_start: 4.099999997764826,
    response_start: 317.0999999977648,
    response_end: 317.79999999701977,
    decoded_body_size: 58346,
    encoded_body_size: 58346,
    initiator_type: 'navigation',
    next_hop_protocol: 'http/1.1',
    render_blocking_status: 'blocking',
    response_status: 0,
    transfer_size: 58646,
    largest_contentful_paint_element: '',
    largest_contentful_paint_render_time: 0,
    largest_contentful_paint_load_time: 0,
    largest_contentful_paint_size: 0,
    largest_contentful_paint_id: '',
    largest_contentful_paint_url: '',
    dom_complete: 626.7999999970198,
    dom_content_loaded_event: 0,
    dom_interactive: 449.19999999925494,
    load_event_end: 626.7999999970198,
    load_event_start: 626.7999999970198,
    redirect_count: 0,
    navigation_type: '',
    unload_event_end: 344,
    unload_event_start: 344,
}

const Template: ComponentStory<typeof PerfBlock> = (args) => (
    <div className="web-performance min-w-120">
        <div className="waterfall-chart">
            <div className="relative">
                <div className="marker-row">
                    <PerfBlock {...args} />
                </div>
            </div>
        </div>
    </div>
)

export const PerfBlockWithoutPerformanceDetails = Template.bind({})
PerfBlockWithoutPerformanceDetails.args = {
    resourceTiming: {
        item: new URL('http://localhost:8234/static/chunk-MCOK6TO3.js'),
        performanceParts: {},
        entry: performanceEvent,
        color: 'hsl(205, 100%, 74%)',
    },
}

export const PerfBlockWithPerformanceDetails = Template.bind({})
PerfBlockWithPerformanceDetails.args = {
    resourceTiming: {
        item: 'the page',
        performanceParts: {
            'dns lookup': {
                start: 18,
                end: 79,
                color: 'hsl(235, 60%, 34%)',
            },
            'connection time': {
                start: 79,
                end: 110,
                color: 'hsl(235, 60%, 34%)',
            },
            'tls time': {
                start: 90,
                end: 110,
                color: 'hsl(235, 60%, 34%)',
                reducedHeight: true,
            },
            'waiting for first byte (TTFB)': {
                start: 110,
                end: 450,
                color: 'hsl(235, 60%, 34%)',
            },
            'receiving response': {
                start: 450,
                end: 502.8,
                color: 'hsl(235, 60%, 34%)',
            },
        },
        entry: performanceEvent,
    },
}
