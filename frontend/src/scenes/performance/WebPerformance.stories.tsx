import { Meta } from '@storybook/react'
import eventsResponse from './__mocks__/eventsResponse.json'

import React, { useEffect } from 'react'
import { Row } from 'antd'
import { MinimalPerformanceResourceTiming } from 'scenes/performance/webPerformanceLogic'
import { mswDecorator } from '~/mocks/browser'
import { router } from 'kea-router'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'
import { PerfBlock } from 'scenes/performance/WebPerformanceWaterfallChart'

export default {
    title: 'Scenes-App/Web Performance',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'canvas' },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:projectId/events': {
                    results: eventsResponse,
                },
            },
        }),
    ],
} as Meta

export const WebPerformance_ = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.webPerformance())
    })
    return <App />
}

export const PerformanceBlockWithNoPerformanceDetails = (): JSX.Element => (
    <div className="performance-waterfall">
        <div className="waterfall-chart">
            <Row key={0} className={'marker-row'}>
                <PerfBlock
                    max={1000}
                    resourceTiming={{
                        item: new URL('http://localhost:8234/static/chunk-MCOK6TO3.js'),
                        performanceParts: {},
                        entry: {
                            name: 'http://localhost:8234/static/chunk-MCOK6TO3.js',
                            startTime: 436.4,
                            duration: 10.9,
                            initiatorType: 'other',
                            fetchStart: 436.4,
                            responseEnd: 447.3,
                        } as MinimalPerformanceResourceTiming,
                        color: 'hsl(205, 100%, 74%)',
                    }}
                />
            </Row>
        </div>
    </div>
)

export const PerformanceBlockWithPerformanceDetails = (): JSX.Element => (
    <div className="performance-waterfall">
        <div className="waterfall-chart">
            <Row key={0} className={'marker-row'}>
                <PerfBlock
                    max={700}
                    resourceTiming={{
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
                        entry: {
                            name: 'http://127.0.0.1:8000/data-management/events',
                            entryType: 'navigation',
                            duration: 510,
                            initiatorType: 'navigation',
                            fetchStart: 18,
                            domainLookupStart: 18,
                            domainLookupEnd: 79,
                            connectStart: 79,
                            connectEnd: 110,
                            secureConnectionStart: 90,
                            requestStart: 110,
                            responseStart: 450,
                            responseEnd: 502.8,
                            transferSize: 35115,
                            encodedBodySize: 34815,
                            decodedBodySize: 34815,
                            unloadEventStart: 502.8,
                            unloadEventEnd: 503.8,
                            domInteractive: 505,
                            domContentLoadedEventStart: 507,
                            domContentLoadedEventEnd: 510,
                            domComplete: 510,
                            loadEventStart: 510,
                            loadEventEnd: 510,
                            type: 'reload',
                        } as PerformanceNavigationTiming,
                    }}
                />
            </Row>
        </div>
    </div>
)
