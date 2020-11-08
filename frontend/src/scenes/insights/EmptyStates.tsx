import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import React from 'react'
import imgEmptyLineGraph from 'public/empty-line-graph.svg'
import imgEmptyLineGraphDark from 'public/empty-line-graph-dark.svg'
import { QuestionCircleOutlined } from '@ant-design/icons'

export function LineGraphEmptyState({ color }: { color: string }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    return (
        <>
            {!featureFlags['1694-dashboards'] && (
                <p style={{ textAlign: 'center', paddingTop: '4rem' }}>
                    We couldn't find any matching events. Try changing dates or pick another action or event.
                </p>
            )}
            {featureFlags['1694-dashboards'] && (
                <div className="text-center" style={{ height: '100%' }}>
                    <img
                        src={color === 'white' ? imgEmptyLineGraphDark : imgEmptyLineGraph}
                        alt=""
                        style={{ maxHeight: '100%', maxWidth: '80%', opacity: 0.5 }}
                    />
                    <div style={{ textAlign: 'center', fontWeight: 'bold', marginTop: 16 }}>
                        Seems like there's no data to show this graph yet{' '}
                        <a
                            target="_blank"
                            href="https://posthog.com/docs/features/trends"
                            style={{ color: color === 'white' ? 'rgba(0, 0, 0, 0.85)' : 'white' }}
                        >
                            <QuestionCircleOutlined />
                        </a>
                    </div>
                </div>
            )}
        </>
    )
}
