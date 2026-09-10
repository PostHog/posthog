import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import {
    createInsightStory,
    insightSceneMswDecorator,
    insightSceneStoryParameters,
} from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'
import { AnnotationScope, RawAnnotationType } from '~/types'

import __trendsLine from '../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'

const ANNOTATION_CONTENT: [number, string, string][] = [
    [1001, '2022-03-05T09:00:00Z', 'Pricing page redesign shipped'],
    [1002, '2022-03-06T14:30:00Z', 'Signup flow experiment started'],
    [1003, '2022-03-07T08:15:00Z', 'Release 2.4 rolled out to all regions'],
    [1004, '2022-03-08T11:00:00Z', 'Checkout latency incident'],
    [1005, '2022-03-09T16:45:00Z', 'Spring campaign launch'],
]

const ANNOTATIONS: RawAnnotationType[] = ANNOTATION_CONTENT.map(([id, dateMarker, content]) => ({
    id,
    content,
    date_marker: dateMarker,
    scope: AnnotationScope.Project,
    created_at: '2022-03-01T00:00:00Z',
    updated_at: '2022-03-01T00:00:00Z',
    dashboard_item: null,
    creation_type: 'USR',
    deleted: false,
}))

const withAnnotations = mswDecorator({
    get: {
        '/api/projects/:team_id/annotations/': () => [
            200,
            { count: ANNOTATIONS.length, next: null, previous: null, results: ANNOTATIONS },
        ],
    },
})

function trendsLineInsight(visibleAnnotationIds?: number[]): Record<string, any> {
    const insight = __trendsLine as Record<string, any>
    return {
        ...insight,
        query: {
            ...insight.query,
            source: {
                ...insight.query.source,
                interval: 'day',
                dateRange: { date_from: '-7d' },
                trendsFilter: { ...insight.query.source.trendsFilter, visibleAnnotationIds },
            },
        },
    }
}

async function openDisplayOptions(): Promise<void> {
    const optionsButton = await waitFor(
        () => {
            const button = Array.from(document.body.querySelectorAll<HTMLElement>('button[aria-label="Options"]')).find(
                (candidate) => candidate.offsetParent !== null
            )
            if (!button) {
                throw new Error('Options button not ready')
            }
            return button
        },
        { timeout: 10_000 }
    )
    await userEvent.click(optionsButton)
    await waitFor(
        () => {
            if (!document.body.querySelector('[data-attr="insight-visible-annotations"]')) {
                throw new Error('Annotations picker not ready')
            }
        },
        { timeout: 10_000 }
    )
}

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Scenes-App/Insights/TrendsAnnotationsPicker',
    parameters: insightSceneStoryParameters,
    decorators: [insightSceneMswDecorator, withAnnotations],
}

export default meta

export const AllAnnotations: Story = {
    render: createInsightStory(trendsLineInsight() as any, 'edit'),
    parameters: {
        ...meta.parameters,
        testOptions: { ...meta.parameters?.testOptions, waitForSelector: '[data-attr="insight-visible-annotations"]' },
    },
    play: openDisplayOptions,
}

export const SelectedAnnotations: Story = {
    render: createInsightStory(trendsLineInsight([1002, 1004]) as any, 'edit'),
    parameters: {
        ...meta.parameters,
        testOptions: { ...meta.parameters?.testOptions, waitForSelector: '[data-attr="insight-visible-annotations"]' },
    },
    play: openDisplayOptions,
}
