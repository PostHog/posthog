import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'
import { ChartDisplayType } from '~/types'

type Story = StoryObj<{}>

const changeChartInsight = {
    id: 901,
    short_id: 'changechart',
    query: {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            interval: 'day',
            filterTestAccounts: false,
            properties: { type: 'AND', values: [] },
            series: [{ event: '$pageview', kind: 'EventsNode', name: '$pageview' }],
            breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
            compareFilter: { compare: true },
            dateRange: { date_from: '-7d', explicitDate: true },
            trendsFilter: { display: ChartDisplayType.ChangeChart, resultCustomizationBy: 'value' },
            version: 2,
        },
        full: true,
    },
    result: [
        {
            action: { id: '$pageview', type: 'events', name: '$pageview', order: 0 },
            label: '$pageview',
            count: 100,
            aggregated_value: 100,
            data: [],
            days: [],
            labels: [],
            breakdown_value: 'New York',
            compare: true,
            compare_label: 'current',
        },
        {
            action: { id: '$pageview', type: 'events', name: '$pageview', order: 0 },
            label: '$pageview',
            count: 90,
            aggregated_value: 90,
            data: [],
            days: [],
            labels: [],
            breakdown_value: 'New York',
            compare: true,
            compare_label: 'previous',
        },
        {
            action: { id: '$pageview', type: 'events', name: '$pageview', order: 0 },
            label: '$pageview',
            count: 45,
            aggregated_value: 45,
            data: [],
            days: [],
            labels: [],
            breakdown_value: 'Los Angeles',
            compare: true,
            compare_label: 'current',
        },
        {
            action: { id: '$pageview', type: 'events', name: '$pageview', order: 0 },
            label: '$pageview',
            count: 60,
            aggregated_value: 60,
            data: [],
            days: [],
            labels: [],
            breakdown_value: 'Los Angeles',
            compare: true,
            compare_label: 'previous',
        },
    ],
}

const meta: Meta = {
    title: 'Scenes-App/Insights/ChangeChart',
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            snapshotBrowsers: ['chromium'],
            viewport: {
                width: 1300,
                height: 720,
            },
        },
        viewMode: 'story',
        mockDate: '2022-03-11',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/persons/retention': sampleRetentionPeopleResponse,
                '/api/environments/:team_id/persons/properties': samplePersonProperties,
                '/api/projects/:team_id/groups_types': [],
            },
            post: {
                '/api/projects/:team_id/cohorts/': { id: 1 },
            },
        }),
    ],
}

export default meta

export const Default: Story = createInsightStory(changeChartInsight)
Default.parameters = { testOptions: { waitForSelector: '[data-attr=change-chart]' } }
