import type { Meta, StoryObj } from '@storybook/react'
import React, { ReactNode } from 'react'

import { Graph, Overview, Table } from '../components'
import { exampleGraphVisitorsResponse, exampleOverviewResponse, exampleTableResponse } from './exampleData'

const meta: Meta = {
    title: 'Analytics/Dashboard',
    parameters: {
        layout: 'padded',
        docs: {
            description: {
                component: 'Complete analytics dashboard showcasing all components together.',
            },
        },
    },
}

export default meta
type Story = StoryObj

export const CompleteDashboard: Story = {
    render: (): ReactNode => (
        <div className="space-y-8 max-w-6xl">
            <div>
                <Overview response={exampleOverviewResponse} />
            </div>

            <div>
                <Graph response={exampleGraphVisitorsResponse} height={300} />
            </div>

            <div>
                <h2 className="text-2xl font-bold mb-4">Pages</h2>
                <Table response={exampleTableResponse} currentPage={1} pageSize={10} />
            </div>
        </div>
    ),
    parameters: {
        docs: {
            description: {
                story: 'A complete analytics dashboard showing how all components work together.',
            },
        },
    },
}

export const CompleteDashboardDark: Story = {
    render: (): ReactNode => (
        <div className="dark">
            <div className="bg-background text-foreground min-h-screen p-6">
                <div className="space-y-8 max-w-6xl">
                    <div>
                        <Overview response={exampleOverviewResponse} />
                    </div>

                    <div>
                        <Graph response={exampleGraphVisitorsResponse} height={300} />
                    </div>

                    <div>
                        <h2 className="text-2xl font-bold mb-4">Pages</h2>
                        <Table response={exampleTableResponse} currentPage={1} pageSize={10} />
                    </div>
                </div>
            </div>
        </div>
    ),
    parameters: {
        docs: {
            description: {
                story: 'A complete analytics dashboard in dark mode, demonstrating how semantic CSS variables adapt the theme.',
            },
        },
    },
}

export const LoadingStates: Story = {
    render: (): ReactNode => (
        <div className="space-y-8 max-w-6xl">
            <div>
                <Overview loading />
            </div>

            <div>
                <Graph loading height={300} />
            </div>

            <div>
                <h2 className="text-2xl font-bold mb-4">Paths</h2>
                <Table loading />
            </div>
        </div>
    ),
    parameters: {
        docs: {
            description: {
                story: 'All components in their loading states.',
            },
        },
    },
}

export const ErrorStates: Story = {
    render: (): ReactNode => (
        <div className="space-y-8 max-w-6xl">
            <div>
                <Overview
                    error={{
                        error: 'Failed to load metrics',
                        details: 'API connection error',
                    }}
                />
            </div>

            <div>
                <Graph
                    error={{
                        error: 'Chart data unavailable',
                        details: 'Service temporarily down',
                    }}
                    height={300}
                />
            </div>

            <div>
                <h2 className="text-2xl font-bold mb-4">Paths</h2>
                <Table
                    error={{
                        error: 'Table data failed to load',
                        details: 'Database timeout',
                    }}
                />
            </div>
        </div>
    ),
    parameters: {
        docs: {
            description: {
                story: 'All components showing error states.',
            },
        },
    },
}

export const CustomerBrand: Story = {
    render: (): ReactNode => {
        // Set CSS variables on document root for the story immediately
        const root = document.documentElement

        // Set the CSS variables synchronously
        root.style.setProperty('--ph-embed-chart-line-color', '331 92% 91%')
        root.style.setProperty('--ph-embed-chart-line-color-muted', '331 92% 70%')
        root.style.setProperty('--ph-embed-chart-grid', '216 73% 91%')
        root.style.setProperty('--ph-embed-chart-text', '225 88% 25%')
        root.style.setProperty('--ph-embed-chart-gradient-start', '331 92% 91%')
        root.style.setProperty('--ph-embed-chart-gradient-end', '23 92% 90%')
        root.style.setProperty('--ph-embed-positive', '32 86% 45%')
        root.style.setProperty('--ph-embed-negative', '11 82% 55%')
        root.style.setProperty('--ph-embed-neutral', '225 88% 35%')
        root.style.setProperty('--ph-embed-table-fill-color', '23 92% 90%')

        // Cleanup function to reset CSS variables
        React.useEffect(() => {
            return () => {
                root.style.removeProperty('--ph-embed-chart-line-color')
                root.style.removeProperty('--ph-embed-chart-line-color-muted')
                root.style.removeProperty('--ph-embed-chart-grid')
                root.style.removeProperty('--ph-embed-chart-text')
                root.style.removeProperty('--ph-embed-chart-gradient-start')
                root.style.removeProperty('--ph-embed-chart-gradient-end')
                root.style.removeProperty('--ph-embed-positive')
                root.style.removeProperty('--ph-embed-negative')
                root.style.removeProperty('--ph-embed-neutral')
                root.style.removeProperty('--ph-embed-table-fill-color')
            }
        }, [root.style])

        return (
            <div className="space-y-8 max-w-6xl">
                <div
                    className="min-h-screen p-8"
                    style={
                        {
                            background:
                                'linear-gradient(135deg, hsl(216 73% 91%) 0%, hsl(247 63% 92%) 25%, hsl(331 92% 91%) 50%, hsl(23 92% 90%) 75%, hsl(32 86% 88%) 100%)',
                            backgroundAttachment: 'fixed',
                        } as React.CSSProperties
                    }
                >
                    <div className="space-y-8">
                        <div>
                            <Overview response={exampleOverviewResponse} />
                        </div>

                        <div>
                            <Graph response={exampleGraphVisitorsResponse} height={300} />
                        </div>

                        <div>
                            <h2 className="text-2xl font-bold mb-4 text-white drop-shadow-lg">Pages</h2>
                            <Table response={exampleTableResponse} currentPage={1} pageSize={10} />
                        </div>
                    </div>
                </div>
            </div>
        )
    },
    parameters: {
        docs: {
            description: {
                story: 'A beautiful analytics dashboard using Customer-inspired brand colors with a soft gradient background and glassmorphism effects.',
            },
        },
    },
}
