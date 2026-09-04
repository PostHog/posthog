import { Meta, StoryObj } from '@storybook/react'

import { GitHubRepoSummary } from './GitHubRepoSummary'

const meta: Meta<typeof GitHubRepoSummary> = {
    title: 'Components/Integrations/GitHubRepoSummary',
    component: GitHubRepoSummary,
    args: {
        installationId: '12345',
        accountType: 'Organization',
        accountName: 'PostHog',
        loading: false,
        repoNames: [],
    },
    tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof GitHubRepoSummary>

export const Loading: Story = {
    args: { loading: true },
    // The spinner never stops in this story, so the runner must not wait it out.
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

export const NoRepositories: Story = {}

export const SelectedRepositories: Story = {
    args: {
        repositorySelection: 'selected',
        repoNames: ['posthog', 'posthog-js', 'posthog.com', 'posthog-python', 'code'],
    },
}

export const AllRepositories: Story = {
    args: {
        repositorySelection: 'all',
        repoNames: ['posthog', 'posthog-js', 'posthog.com'],
        total: 712,
    },
}
