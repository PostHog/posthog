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
                            item: 'http://localhost:8234/static/chunk-MCOK6TO3.js',
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
                        max={1000}
                        resourceTiming={{
                            item: 'the page',
                            performanceParts: {
                                'dns lookup': {
                                    start: 7.8,
                                    end: 7.8,
                                    color: 'hsl(235, 60%, 34%)',
                                },
                                'connection time': {
                                    start: 7.8,
                                    end: 7.9,
                                    color: 'hsl(235, 60%, 34%)',
                                },
                                'waiting for first byte (TTFB)': {
                                    start: 8.1,
                                    end: 193,
                                    color: 'hsl(235, 60%, 34%)',
                                },
                            },
                            entry: {
                                name: 'http://127.0.0.1:8000/events/stats',
                                entryType: 'navigation',
                                duration: 336.8,
                                initiatorType: 'navigation',
                                fetchStart: 6.1,
                                domainLookupStart: 7.8,
                                domainLookupEnd: 7.8,
                                connectStart: 7.8,
                                connectEnd: 7.9,
                                requestStart: 8.1,
                                responseStart: 193,
                                responseEnd: 193.5,
                                transferSize: 35115,
                                encodedBodySize: 34815,
                                decodedBodySize: 34815,
                                unloadEventStart: 199.9,
                                unloadEventEnd: 207.1,
                                domInteractive: 271.3,
                                domContentLoadedEventStart: 271.3,
                                domContentLoadedEventEnd: 271.3,
                                domComplete: 336.7,
                                loadEventStart: 336.8,
                                loadEventEnd: 336.8,
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
