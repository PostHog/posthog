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
