import '../Bets.scss'

import type { Meta, StoryObj } from '@storybook/react'

import 'scenes/project-homepage/today/Today.scss'

import { BetsNextAction } from './BetsNextAction'

const meta: Meta<typeof BetsNextAction> = {
    title: 'Products/Bets/Next action',
    component: BetsNextAction,
    decorators: [
        (Story) => (
            <div className="Today Bets Today__page p-6" data-quill>
                <ul className="mt-5 list-none p-0">
                    <Story />
                </ul>
            </div>
        ),
    ],
    args: {
        item: {
            id: 'review-share',
            bet_id: '00000000-0000-4000-8000-000000000001',
            bet_title: 'Make sharing easier',
            title: 'Offer a share link right after upload',
            description: 'Review and merge the pull request when you are happy with it.',
            label: 'Pull request',
            url: 'https://github.com/example/app/pull/12',
            work_id: '00000000-0000-4000-8000-000000000002',
        },
    },
}
export default meta

type Story = StoryObj<typeof meta>

export const PullRequest: Story = {}
export const BudgetDecision: Story = {
    args: {
        item: {
            ...meta.args!.item!,
            id: 'review-budget',
            title: 'The budget is used up',
            description: 'Add budget to keep going, or close the bet.',
            label: 'Budget',
            url: '',
            work_id: null,
        },
    },
}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div style={{ width: 520 }}>
                <Story />
            </div>
        ),
    ],
}
