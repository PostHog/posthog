import { Meta, StoryFn } from '@storybook/react'
import { CapturedNetworkRequest } from 'posthog-js'

import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { mapRRWebNetworkRequest } from 'scenes/session-recordings/apm/performance-event-utils'
import {
    BodyDisplay,
    HeadersDisplay,
    ItemPerformanceEvent,
    ItemPerformanceEventDetail,
    ItemPerformanceEventProps,
} from 'scenes/session-recordings/apm/playerInspector/ItemPerformanceEvent'

import { mswDecorator } from '~/mocks/browser'
import { PerformanceEvent } from '~/types'

const meta: Meta<typeof ItemPerformanceEvent> = {
    title: 'Components/ItemPerformanceEvent',
    component: ItemPerformanceEvent,
    decorators: [
        mswDecorator({
            get: {},
        }),
    ],
}
export default meta

const BasicTemplate: StoryFn<typeof ItemPerformanceEvent> = (props: Partial<ItemPerformanceEventProps>) => {
    props.item = props.item || undefined

    const propsToUse = props as ItemPerformanceEventProps

    return (
        <div className="flex flex-col gap-2 min-w-96">
            <h3>Collapsed</h3>
            <ItemPerformanceEvent {...propsToUse} />
            <LemonDivider />
            <h3>Expanded</h3>
            <ItemPerformanceEventDetail {...propsToUse} />
        </div>
    )
}

const exampleWithPerformanceObserverValues = mapRRWebNetworkRequest(
    {
        connectEnd: 5842.9000000059605,
        connectStart: 5842.9000000059605,
        decodedBodySize: 3,
        deliveryType: 'cache',
        domainLookupEnd: 5842.9000000059605,
        domainLookupStart: 5842.9000000059605,
        duration: 378.59999999403954,
        encodedBodySize: 3,
        endTime: 6222,
        entryType: 'resource',
        fetchStart: 5842.9000000059605,
        firstInterimResponseStart: 0,
        initiatorType: 'fetch',
        method: 'GET',
        name: 'https://posthog.com/api/signup-count',
        nextHopProtocol: 'h2',
        redirectEnd: 0,
        redirectStart: 0,
        renderBlockingStatus: 'non-blocking',
        requestBody: '',
        requestHeaders: {},
        requestStart: 5844.0999999940395,
        responseBody: '240',
        responseEnd: 6221.5,
        responseHeaders: {
            age: '0',
            'cache-control': 'public, max-age=0, must-revalidate',
            'content-length': '3',
            'content-type': 'application/json; charset=utf-8',
            date: 'Tue, 17 Sep 2024 22:50:13 GMT',
            etag: 'W/"3-yukeRa7YDzo/4oXDyMGn542C1HM"',
            server: 'Vercel',
            'x-vercel-cache': 'MISS',
            'x-vercel-id': '12345',
        },
        responseStart: 6220.70000000298,
        responseStatus: 200,
        secureConnectionStart: 5842.9000000059605,
        serverTiming: [],
        startTime: 5843,
        status: 200,
        timeOrigin: 1726613407403,
        timestamp: 1726613413245,
        transferSize: 300,
        workerStart: 0,
    } as unknown as CapturedNetworkRequest, // TODO should not need this cast... the type is slightly off here!
    'window_id',
    1726613413245
)

const exampleWithoutPerformanceObserverValues = {
    end_time: 859613,
    method: 'GET',
    name: 'https://api.company.com/v1/counts',
    request_body: null,
    request_headers: {
        Accept: 'application/json',
        Authorization: 'redacted',
        'Authorization-CS': 'false',
        'Authorization-CS-debug': 'false',
        'GA-Client': '12345',
        'X-Posthog-Session-ID': '0191ff59-4b70-73ca-889f-87bbafc17c31',
        baggage:
            'sentry-environment=production,sentry-release=12345,sentry-public_key=12345,sentry-trace_id=12345,sentry-sample_rate=0.01,sentry-transaction=%2Fdashboard%2F,sentry-sampled=false',
        'sentry-trace': '12345-12345-0',
    },
    response_body: '{"data":{"unread_messages":7,"unassigned_tasks":0,"thingies":0}}',
    response_headers: {
        'cache-control': 'no-cache, private',
        'content-type': 'application/json',
    },
    start_time: 858859,
    response_status: 200,
    time_origin: '1726567602079',
    timestamp: 1726568460938,
}

export const Default = BasicTemplate.bind({})
Default.args = {
    item: exampleWithPerformanceObserverValues,
}

export const NoPerformanceObserverCapturedData = BasicTemplate.bind({})
NoPerformanceObserverCapturedData.args = {
    item: {
        ...exampleWithoutPerformanceObserverValues,
        // mapping isn't run here but would have added raw
        raw: exampleWithoutPerformanceObserverValues,
    } as unknown as PerformanceEvent,
}

export function InitialHeadersDisplay(): JSX.Element {
    return <HeadersDisplay request={undefined} response={undefined} isInitial={true} />
}

export function InitialBodyDisplay(): JSX.Element {
    return (
        <BodyDisplay
            content={undefined}
            headers={undefined}
            emptyMessage="Response captured before PostHog was initialized"
        />
    )
}
