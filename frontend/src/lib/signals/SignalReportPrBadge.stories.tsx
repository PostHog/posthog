import type { Meta, StoryObj } from '@storybook/react'

import type { PullRequestCiStatusEnumApi } from 'products/signals/frontend/generated/api.schemas'

import type { PrBadgeState } from './prState'
import { PrBadge } from './SignalReportPrBadge'

const meta: Meta<typeof PrBadge> = {
    title: 'Components/Signal report PR badge',
    component: PrBadge,
}
export default meta

type Story = StoryObj<typeof PrBadge>

const LIFECYCLE: PrBadgeState[] = ['open', 'merged', 'closed']
const CI_STATUSES: (PullRequestCiStatusEnumApi | undefined)[] = [undefined, 'passing', 'failing', 'pending', 'none']

// Every pill a report list can show. Only an open pull request carries a CI glyph, so the merged and
// closed rows are expected to look the same across the CI columns.
export const States: Story = {
    render: () => (
        <div className="flex flex-col gap-3 p-4">
            {LIFECYCLE.map((state) => (
                <div key={state} className="flex items-center gap-3">
                    <span className="w-16 text-xs text-secondary">{state}</span>
                    {CI_STATUSES.map((ciStatus) => (
                        <PrBadge
                            key={ciStatus ?? 'unknown'}
                            prNumber="1234"
                            prUrl="https://github.com/PostHog/posthog/pull/1234"
                            state={state}
                            ciStatus={ciStatus}
                        />
                    ))}
                </div>
            ))}
        </div>
    ),
}
