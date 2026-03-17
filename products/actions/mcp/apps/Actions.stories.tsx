import { McpThemeDecorator } from '@common/mosaic/storybook/decorator'
import type { Meta, StoryObj } from '@storybook/react'

import { ActionListView, type ActionData, type ActionListData, ActionView } from './index'

const meta: Meta = {
    title: 'MCP Apps/Actions',
    decorators: [McpThemeDecorator],
    parameters: {
        testOptions: {
            // McpThemeDecorator doesn't have dark mode built-in by default so just disable this to avoid duplicated snapshots
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

const urlMatchingAction: ActionData = {
    id: 1,
    name: 'Visited pricing page',
    description: 'Triggers when a user visits any pricing-related page.',
    tags: ['marketing', 'funnel'],
    created_at: '2025-10-15T09:00:00Z',
    created_by: { first_name: 'Jane', email: 'jane@posthog.com' },
    steps: [
        {
            event: '$pageview',
            url: '/pricing',
            url_matching: 'contains',
        },
    ],
    _posthogUrl: 'https://us.posthog.com/project/1/data-management/actions/1',
}

const multiStepAction: ActionData = {
    id: 2,
    name: 'Signed up via CTA',
    description: 'User clicked a signup CTA button and completed the form.',
    tags: ['growth'],
    pinned_at: '2025-12-01T00:00:00Z',
    created_at: '2025-09-01T09:00:00Z',
    created_by: { first_name: 'Alex' },
    steps: [
        {
            event: '$autocapture',
            selector: 'button.cta-signup',
            text: 'Sign up',
            text_matching: 'exact',
        },
        {
            event: 'signup_completed',
        },
    ],
    _posthogUrl: 'https://us.posthog.com/project/1/data-management/actions/2',
}

const simpleAction: ActionData = {
    id: 3,
    name: 'Dashboard viewed',
    created_at: '2025-11-01T09:00:00Z',
    steps: [{ event: 'dashboard_viewed' }],
}

export const UrlMatching: Story = {
    render: () => <ActionView action={urlMatchingAction} />,
    storyName: 'Action with URL matching',
}

export const MultiStep: Story = {
    render: () => <ActionView action={multiStepAction} />,
    storyName: 'Pinned action with multiple steps',
}

export const Simple: Story = {
    render: () => <ActionView action={simpleAction} />,
    storyName: 'Simple action',
}

const sampleListData: ActionListData = {
    results: [urlMatchingAction, multiStepAction, simpleAction],
    _posthogUrl: 'https://us.posthog.com/project/1/data-management/actions',
}

export const List: Story = {
    render: () => <ActionListView data={sampleListData} />,
    storyName: 'Action list',
}
