import clsx from 'clsx'
import React from 'react'

import { LemonDialog } from '@posthog/lemon-ui'

import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'

import { Query } from '~/queries/Query/Query'

import type { MultiVisualizationInsight } from './multiVisualizationInsights'

export function openMultiVisualizationModal(insights: MultiVisualizationInsight[]): void {
    LemonDialog.open({
        title: 'Insights',
        content: <MultiVisualizationModal insights={insights} />,
        primaryButton: null,
        width: '90%',
        maxWidth: 1400,
    })
}

function MultiVisualizationModal({ insights: messages }: { insights: MultiVisualizationInsight[] }): JSX.Element {
    const [selectedIndex, setSelectedIndex] = React.useState(0)

    return (
        <div className="flex">
            {/* Sidebar with visualization list */}
            <div className="w-64 border-r pr-4 overflow-y-auto">
                <h5 className="text-xs font-semibold text-muted mb-3">VISUALIZATIONS</h5>
                <div className="space-y-1">
                    {messages.map((item, index) => (
                        <button
                            key={index}
                            onClick={() => setSelectedIndex(index)}
                            className={clsx(
                                'w-full text-left p-2 rounded transition-colors text-sm',
                                selectedIndex === index
                                    ? 'bg-primary text-primary-inverted font-semibold'
                                    : 'hover:bg-surface-secondary'
                            )}
                        >
                            {item.title}
                        </button>
                    ))}
                </div>
            </div>

            {/* Main content area */}
            <div className="flex-1 pl-4 overflow-auto">
                {messages[selectedIndex] && (
                    <>
                        <h4 className="text-base font-semibold mb-3">
                            <TopHeading query={messages[selectedIndex].query} />
                        </h4>
                        <div className="min-h-80">
                            <Query query={messages[selectedIndex].query} readOnly embedded />
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}
