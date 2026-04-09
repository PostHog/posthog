import { Meta, StoryObj } from '@storybook/react'
import { BindLogic, Provider, useActions, useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType, InsightShortId } from '~/types'

import { ChangeChartOptions } from './ChangeChartOptions'

type Story = StoryObj<{}>

function ChangeChartOptionsStory(): JSX.Element {
    const insightProps = { dashboardItemId: 'change-chart-options' as InsightShortId }
    const vizLogic = insightVizDataLogic(insightProps)

    useMountedLogic(vizLogic)
    const { updateQuerySource, updateVizSpecificOptions } = useActions(vizLogic)

    useEffect(() => {
        updateQuerySource({
            kind: NodeKind.TrendsQuery,
            interval: 'day',
            filterTestAccounts: false,
            properties: { type: 'AND', values: [] },
            series: [{ event: '$pageview', kind: NodeKind.EventsNode, name: '$pageview' }],
            breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
            compareFilter: { compare: true },
            dateRange: { date_from: '-7d', explicitDate: true },
            trendsFilter: { display: ChartDisplayType.ChangeChart },
            version: 2,
        })
        updateVizSpecificOptions({
            [ChartDisplayType.ChangeChart]: {
                displayMode: 'relative',
                orderBy: 'change',
                orderDirection: 'desc',
                showCurrentValue: true,
            },
        })
    }, [updateQuerySource, updateVizSpecificOptions])

    return (
        <Provider>
            <BindLogic logic={insightLogic} props={insightProps}>
                <div className="w-72 rounded border border-primary bg-surface-primary p-2">
                    <ChangeChartOptions />
                </div>
            </BindLogic>
        </Provider>
    )
}

const meta: Meta = {
    title: 'Components/ChangeChartOptions',
    parameters: {
        viewMode: 'story',
    },
    render: () => <ChangeChartOptionsStory />,
}

export default meta

export const Default: Story = {}
