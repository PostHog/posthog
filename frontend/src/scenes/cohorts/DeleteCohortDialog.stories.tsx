import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import type { CohortUsedInResponseApi } from 'products/cohorts/frontend/generated/api.schemas'

import { DeleteCohortDialog } from './DeleteCohortDialog'

const emptyBlock = { results: [], total: 0, has_more: false }

const usedIn: CohortUsedInResponseApi = {
    feature_flags: {
        results: [
            { id: 1, key: 'new-checkout', name: 'New checkout', active: true },
            { id: 2, key: 'paused-banner', name: 'Paused banner', active: false },
        ],
        total: 2,
        has_more: false,
    },
    insights: {
        results: [{ id: 5, short_id: 'abc123', name: 'Weekly signups' }],
        total: 1,
        has_more: false,
    },
    cohorts: emptyBlock,
    test_account_filters: {
        results: [{ id: 42, name: 'Staging' }],
        total: 1,
        has_more: false,
    },
}

const meta: Meta<typeof DeleteCohortDialog> = {
    component: DeleteCohortDialog,
    title: 'Scenes-App/People/Delete cohort dialog',
    // In the app the dialog sits in a LemonModal, which is never narrower than 28rem. Rendering the
    // bare component lets it shrink to its text, so the snapshot would wrap at a width no user sees.
    decorators: [
        (Story) => (
            <div className="w-[28rem]">
                <Story />
            </div>
        ),
    ],
    args: {
        cohortId: 1,
        cohortName: 'Power users',
        onConfirm: () => {},
        closeDialog: () => {},
    },
}
export default meta

type Story = StoryObj<typeof DeleteCohortDialog>

export const Blocked: Story = {
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/cohorts/:id/used_in/': usedIn } })],
}

export const NothingUsesIt: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/cohorts/:id/used_in/': {
                    feature_flags: emptyBlock,
                    insights: emptyBlock,
                    cohorts: emptyBlock,
                    test_account_filters: emptyBlock,
                },
            },
        }),
    ],
}
