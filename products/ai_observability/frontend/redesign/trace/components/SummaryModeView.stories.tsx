import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_SUMMARY, withWidth } from '../storyFixtures'
import { SummaryModeView } from './SummaryModeView'

const meta: Meta<typeof SummaryModeView> = {
    title: 'Scenes-App/AI observability/Trace view/Summary mode',
    component: SummaryModeView,
    args: {
        requesting: false,
        requestError: null,
        consentGiven: true,
        onRequest: () => {},
        onRegenerate: () => {},
        onReload: () => {},
        onSelectStep: () => {},
    },
    decorators: [withWidth(900)],
    parameters: { mockDate: '2026-09-01T10:45:00Z' },
}
export default meta

type Story = StoryObj<typeof SummaryModeView>

export const NoSummary: Story = { args: { state: { status: 'none' } } }
export const NoSummaryWithoutConsent: Story = { args: { state: { status: 'none' }, consentGiven: false } }
export const Pending: Story = {
    args: { state: { status: 'pending' } },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const Ready: Story = { args: { state: { status: 'ready', summary: FIXTURE_SUMMARY } } }
export const ReadyNarrow: Story = {
    args: { state: { status: 'ready', summary: FIXTURE_SUMMARY } },
    decorators: [withWidth(520)],
}
export const RegenerateThrottled: Story = {
    args: { state: { status: 'ready', summary: FIXTURE_SUMMARY }, requestError: 'throttled' },
}
export const Failed: Story = {
    args: {
        state: {
            status: 'failed',
            message: 'The model provider returned an error. Try again in a few minutes.',
            retryable: true,
        },
    },
}
export const LoadError: Story = { args: { state: { status: 'error' } } }
export const Loading: Story = {
    args: { state: { status: 'loading' } },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
