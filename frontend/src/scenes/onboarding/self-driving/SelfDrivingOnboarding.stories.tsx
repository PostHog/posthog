import type { Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { SelfDrivingOnboarding } from './SelfDrivingOnboarding'

const meta: Meta<typeof SelfDrivingOnboarding> = {
    title: 'Scenes-Other/Onboarding/Self-driving',
    component: SelfDrivingOnboarding,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    decorators: [mswDecorator({})],
    render: () => {
        router.actions.replace(urls.onboarding(), { step: 'goals' })
        return <SelfDrivingOnboarding />
    },
}

export default meta

type Story = StoryObj<typeof SelfDrivingOnboarding>

export const UseCasesLight: Story = {
    globals: { theme: 'light' },
    parameters: {
        testOptions: {
            skipDarkMode: true,
            waitForSelector: '[data-attr="self-driving-goal-improve_experience"]',
        },
    },
}

export const UseCasesDark: Story = {
    globals: { theme: 'dark' },
    parameters: {
        testOptions: {
            skipLightMode: true,
            waitForSelector: '[data-attr="self-driving-goal-improve_experience"]',
        },
    },
}
