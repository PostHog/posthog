import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const eightBallUrl = 'api/projects/:team_id/business_knowledge/documents/eight_ball/'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/BusinessKnowledge/MagicEightBall',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        pageUrl: urls.businessKnowledgeMagicEightBall(),
        featureFlags: [
            FEATURE_FLAGS.PRODUCT_BUSINESS_KNOWLEDGE,
            FEATURE_FLAGS.ML_INFERENCE_DECISIONS,
            FEATURE_FLAGS.BUSINESS_KNOWLEDGE_MAGIC_EIGHT_BALL,
        ],
    },
}

export default meta

type Story = StoryObj

async function askQuestion(canvasElement: HTMLElement): Promise<void> {
    const canvas = within(canvasElement)
    await userEvent.type(
        await canvas.findByPlaceholderText('Do we offer refunds on annual plans?'),
        'Do we publish an API changelog?'
    )
    await userEvent.click(canvas.getByRole('button', { name: 'Shake the magic 8 ball' }))
}

async function waitForReveal(canvasElement: HTMLElement): Promise<void> {
    const animations = canvasElement.querySelector('.MagicEightBall__triangle')?.getAnimations() ?? []
    await Promise.all(animations.map((animation) => animation.finished))
}

export const Ready: Story = {}

export const Answered: Story = {
    decorators: [
        mswDecorator({
            post: {
                [eightBallUrl]: [
                    200,
                    {
                        answer: 'Signs point to yes',
                        confidence: 0.83,
                        sources: [
                            {
                                source_id: '11111111-1111-1111-1111-111111111111',
                                source_name: 'Product handbook',
                                document_title: 'Product handbook',
                            },
                        ],
                    },
                ],
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        await askQuestion(canvasElement)
        await within(canvasElement).findByRole('link', { name: 'Product handbook' })
        await waitForReveal(canvasElement)
    },
}

export const NoKnowledge: Story = {
    decorators: [
        mswDecorator({
            post: {
                [eightBallUrl]: [200, { answer: 'Cannot predict now', confidence: 0, sources: [] }],
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        await askQuestion(canvasElement)
        await within(canvasElement).findByText('Nothing in your business knowledge matched, so the ball cannot answer.')
        await waitForReveal(canvasElement)
    },
}

export const Loading: Story = {
    decorators: [
        mswDecorator({
            post: {
                [eightBallUrl]: () => new Promise<never>(() => {}),
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        await askQuestion(canvasElement)
        await within(canvasElement).findByRole('button', { name: 'Shake the magic 8 ball', busy: true })
    },
}

export const Error: Story = {
    decorators: [
        mswDecorator({
            post: {
                [eightBallUrl]: [503, { detail: 'The model is not available.' }],
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        await askQuestion(canvasElement)
        await within(canvasElement).findAllByText(/The ball couldn't answer:/)
    },
}

export const FlagOff: Story = {
    parameters: {
        featureFlags: [FEATURE_FLAGS.PRODUCT_BUSINESS_KNOWLEDGE, FEATURE_FLAGS.ML_INFERENCE_DECISIONS],
    },
    play: async ({ canvasElement }) => {
        await within(canvasElement).findByText('This feature is not enabled for your project.')
    },
}
