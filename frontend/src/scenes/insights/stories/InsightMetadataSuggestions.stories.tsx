import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

import __trendsLine from '../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'

const SUGGESTED_TITLE = 'Unique users with pageviews by browser'

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Scenes-App/Insights/Metadata Suggestions',
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            snapshotBrowsers: ['chromium'],
            viewport: { width: 1300, height: 900 },
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
                '/api/projects/:team_id/tags/': ['growth', 'marketing', 'billing'],
            },
            post: {
                '/api/projects/:team_id/cohorts/': { id: 1 },
                '/api/projects/:team_id/metadata_suggestions/title/': {
                    value: SUGGESTED_TITLE,
                    confidence: 0.82,
                    candidates: ['Pageviews', SUGGESTED_TITLE, 'Daily pageviews'],
                    runner_up: 'Pageviews',
                },
                '/api/projects/:team_id/metadata_suggestions/tags/': {
                    tags: ['growth'],
                    scores: { growth: 0.91, marketing: 0.34, billing: 0.05 },
                },
            },
        }),
    ],
}
export default meta

const flagOn = { featureFlags: [FEATURE_FLAGS.PRODUCT_ANALYTICS_METADATA_SUGGESTIONS] }

async function clickWhenReady(canvasElement: HTMLElement, selector: string): Promise<void> {
    const button = await waitFor(
        () => {
            const element = canvasElement.querySelector<HTMLElement>(selector)
            if (!element) {
                throw new Error(`${selector} not rendered yet`)
            }
            return element
        },
        { timeout: 10_000 }
    )
    await userEvent.click(button)
}

/* eslint-disable @typescript-eslint/no-var-requires */

export const FlagOff: Story = createInsightStory(__trendsLine as any, 'edit', false, { openSidePanel: true })

export const FlagOn: Story = createInsightStory(__trendsLine as any, 'edit', false, { openSidePanel: true })
FlagOn.parameters = { ...flagOn, testOptions: { waitForSelector: '[data-attr="scene-name-suggest-title"]' } }

export const TitleSuggested: Story = createInsightStory(__trendsLine as any, 'edit', false, { openSidePanel: true })
TitleSuggested.parameters = flagOn
TitleSuggested.play = async ({ canvasElement }) => {
    await clickWhenReady(canvasElement, '[data-attr="scene-name-suggest-title"]')
    await waitFor(
        () => {
            const nameField = canvasElement.querySelector<HTMLTextAreaElement>(
                '[data-attr="scene-name-edit-row"] textarea'
            )
            if (nameField?.value !== SUGGESTED_TITLE) {
                throw new Error('Suggested title not applied yet')
            }
        },
        { timeout: 10_000 }
    )
}

export const TagsSuggested: Story = createInsightStory(__trendsLine as any, 'edit', false, { openSidePanel: true })
TagsSuggested.parameters = flagOn
TagsSuggested.play = async ({ canvasElement }) => {
    await clickWhenReady(canvasElement, '[data-attr="insight-tags-suggest"]')
}
