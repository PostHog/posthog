import { Meta, StoryObj } from '@storybook/react'

import { InsightVizStory } from 'scenes/insights/__mocks__/createInsightVizStory'

import __trendsNumber from '~/mocks/fixtures/api/projects/team_id/insights/trendsNumber.json'
import __trendsNumberCompareNullPrevious from '~/mocks/fixtures/api/projects/team_id/insights/trendsNumberCompareNullPrevious.json'
import __trendsNumberEmpty from '~/mocks/fixtures/api/projects/team_id/insights/trendsNumberEmpty.json'

import { BoldNumber } from './BoldNumber'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/BoldNumber',
    component: BoldNumber,
    parameters: {
        layout: 'centered',
        mockDate: '2022-03-11',
        testOptions: {
            snapshotBrowsers: ['chromium'],
            waitForSelector: '.BoldNumber__value',
        },
    },
}
export default meta

export const Default: Story = {
    render: () => <InsightVizStory insight={__trendsNumber as any} />,
}

export const EmptyResult: Story = {
    render: () => <InsightVizStory insight={__trendsNumberEmpty as any} />,
    parameters: { testOptions: { waitForSelector: '[data-attr="insight-empty-state"]' } },
}

export const CompareNullPrevious: Story = {
    render: () => <InsightVizStory insight={__trendsNumberCompareNullPrevious as any} />,
}
