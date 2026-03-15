import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { userEvent, waitFor } from '@storybook/testing-library'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE, toPaginatedResponse } from '~/mocks/handlers'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        pageUrl: urls.experiment('new'),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/experiments/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/experiment_holdouts': [],
                '/api/projects/:team_id/experiment_saved_metrics/': [],
                '/api/projects/:team_id/feature_flags/': toPaginatedResponse([]),
            },
            post: {
                '/api/projects/:team_id/feature_flags/user_blast_radius/': () => [
                    200,
                    { users_affected: 0, total_users: 0 },
                ],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

export const NewExperimentAboutStep: Story = {}

const clickStepButton = async (canvasElement: HTMLElement, stepLabel: string): Promise<void> => {
    const button = await waitFor(
        () => {
            const buttons = canvasElement.querySelectorAll<HTMLButtonElement>('nav[aria-label] button')
            const target = Array.from(buttons).find((b) => b.textContent?.includes(stepLabel))
            if (!target) {
                throw new Error(`Step button "${stepLabel}" not yet rendered`)
            }
            return target
        },
        { timeout: 5000 }
    )
    await userEvent.click(button)
}

export const NewExperimentVariantsStep: StoryFn = () => <App />
NewExperimentVariantsStep.parameters = { pageUrl: urls.experiment('new') }
NewExperimentVariantsStep.play = async ({ canvasElement }) => {
    await clickStepButton(canvasElement, 'Variant rollout')
}

export const NewExperimentAnalyticsStep: StoryFn = () => <App />
NewExperimentAnalyticsStep.parameters = { pageUrl: urls.experiment('new') }
NewExperimentAnalyticsStep.play = async ({ canvasElement }) => {
    await clickStepButton(canvasElement, 'Analytics')
}

export const NewExperimentWithGuide: Story = {}
