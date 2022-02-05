import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

import eventsState from './events.json'
import { PerfBlock, WebPerformance } from 'scenes/performance/WebPerformance'
import React from 'react'
import { Row } from 'antd'
import { MinimalPerformanceResourceTiming } from 'scenes/performance/webPerformanceLogic'

export default {
    title: 'PostHog/Scenes/WebPerformance',
} as Meta

export const WebPerformanceStory = keaStory(WebPerformance, eventsState)

export const PerformanceBlockWithNoPerformanceDetails = keaStory(
    () => (
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
    ),
    eventsState
)

export const PerformanceBlockWithPerformanceDetails = keaStory(
    () => (
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
                                name: 'http://127.0.0.1:8000/events/stats',
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
    ),
    eventsState
)
