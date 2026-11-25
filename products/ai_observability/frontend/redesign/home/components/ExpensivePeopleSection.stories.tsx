import type { Meta, StoryObj } from '@storybook/react'

import { makePersonListItem } from '../../people/testFixtures'
import { ExpensivePeopleSection } from './ExpensivePeopleSection'

const meta: Meta<typeof ExpensivePeopleSection> = {
    title: 'Scenes-App/AI observability/Home/Expensive people section',
    component: ExpensivePeopleSection,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        people: [
            makePersonListItem({ id: 'p1', cost: 128.4 }),
            makePersonListItem({ id: 'p2', cost: 64.2 }),
            makePersonListItem({ id: 'p3', cost: 9.75 }),
            makePersonListItem({ id: 'p4', cost: 0.0125 }),
            makePersonListItem({ id: 'p5', cost: null }),
        ],
        loading: false,
        failed: false,
        needsIdentification: false,
        docsUrl: 'https://posthog.com/docs/ai-observability/installation',
        onRetry: () => {},
        personHref: (person) => `/ai-observability/users?order=cost&person=${person.id}`,
        viewAllHref: '/ai-observability/users?order=cost',
    },
    decorators: [
        (StoryComponent) => (
            <div className="w-80">
                <StoryComponent />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof ExpensivePeopleSection>

export const Ready: Story = {}

export const Empty: Story = { args: { people: [] } }

export const NotSetUp: Story = { args: { people: [], needsIdentification: true } }

export const Failed: Story = { args: { people: null, failed: true } }

export const Loading: Story = { args: { people: null } }

export const Reloading: Story = { args: { loading: true } }
