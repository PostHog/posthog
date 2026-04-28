import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import { BaseMathType, InsightLogicProps } from '~/types'

import { InsightsTable, InsightsTableProps } from './InsightsTable'

type Story = StoryObj<InsightsTableProps>
const meta: Meta<InsightsTableProps> = {
    title: 'Insights/InsightsTable',
    component: InsightsTable,
}
export default meta

let uniqueNode = 0

const renderInsightsTable = (props: any, { parameters }: any): JSX.Element => {
    const [dashboardItemId] = useState(() => `InsightTableStory.${uniqueNode++}`)

    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const insight = require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json')
    const cachedInsight = {
        ...insight,
        short_id: dashboardItemId,
        query: {
            ...insight.query,
            source: {
                ...insight.query.source,
                ...(parameters.mergeQuerySource ? parameters.mergeQuerySource : {}),
            },
        },
    }

    const insightProps = { dashboardItemId, doNotLoad: true, cachedInsight } as InsightLogicProps

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: cachedInsight.query.source,
        key: insightVizDataNodeKey(insightProps),
        cachedResults: getCachedResults(cachedInsight, cachedInsight.query.source),
        doNotLoad: insightProps.doNotLoad,
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <InsightsTable {...props} />
            </BindLogic>
        </BindLogic>
    )
}

export const Default: Story = {
    render: renderInsightsTable,
    args: {},
}

export const IsLegend: Story = {
    render: renderInsightsTable,
    args: {
        isLegend: true,
    },
}

export const Embedded: Story = {
    render: renderInsightsTable,
    args: {
        embedded: true,
    },
}

export const Hourly: Story = {
    render: renderInsightsTable,
    parameters: {
        mergeQuerySource: { interval: 'hour' },
    },
}

export const Aggregation: Story = {
    render: renderInsightsTable,
    parameters: {
        mergeQuerySource: {
            series: [
                {
                    event: '$pageview',
                    kind: 'EventsNode',
                    name: '$pageview',
                    math: BaseMathType.UniqueSessions,
                },
            ],
        },
    },
}

const renderCompareInsightsTable = (props: any): JSX.Element => {
    const [dashboardItemId] = useState(() => `InsightTableStory.${uniqueNode++}`)

    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const insight = require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json')

    // Duplicate each result series with "current" and "previous" compare labels
    const currentResults = insight.result.map((r: Record<string, any>) => ({
        ...r,
        compare_label: 'current',
        compare: true,
    }))
    const previousResults = insight.result.map((r: Record<string, any>) => ({
        ...r,
        compare_label: 'previous',
        compare: true,
        // Simulate different previous period values
        data: r.data.map((v: number) => Math.round(v * 0.8)),
        count: Math.round(r.count * 0.8),
        days: r.days.map((d: string) => {
            const date = new Date(d)
            date.setDate(date.getDate() - r.days.length)
            return date.toISOString().split('T')[0]
        }),
    }))

    const cachedInsight = {
        ...insight,
        short_id: dashboardItemId,
        result: [...currentResults, ...previousResults],
        query: {
            ...insight.query,
            source: {
                ...insight.query.source,
                compareFilter: { compare: true },
            },
        },
    }

    const insightProps = { dashboardItemId, doNotLoad: true, cachedInsight } as InsightLogicProps

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: cachedInsight.query.source,
        key: insightVizDataNodeKey(insightProps),
        cachedResults: getCachedResults(cachedInsight, cachedInsight.query.source),
        doNotLoad: insightProps.doNotLoad,
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <InsightsTable {...props} />
            </BindLogic>
        </BindLogic>
    )
}

export const ComparePrevious: Story = {
    render: renderCompareInsightsTable,
    args: {
        isMainInsightView: true,
    },
}
