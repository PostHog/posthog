import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { Mocks } from '~/mocks/utils'

import { MemberAccountsSection, MemberAccountsSectionProps } from './MemberAccountsSection'

const teammate = (id: number, firstName: string, lastName: string): Record<string, unknown> => ({
    id,
    uuid: `0190a000-0000-0000-0000-00000000000${id}`,
    distinct_id: `teammate-${id}`,
    first_name: firstName,
    last_name: lastName,
    email: `${firstName.toLowerCase()}@example.com`,
})

const account = (id: number, displayName: string, createdBy: Record<string, unknown>, errors = ''): unknown => ({
    id,
    kind: 'google-calendar',
    display_name: displayName,
    config: { display_name: displayName },
    created_at: '2026-10-05T09:30:00Z',
    created_by: createdBy,
    errors,
})

const integrationsMock = (results: unknown[]): Mocks => ({
    get: {
        '/api/projects/:team_id/integrations/': { count: results.length, next: null, previous: null, results },
    },
})

const TEAMMATE_ACCOUNTS = [
    account(2, 'ada@example.com', teammate(2, 'Ada', 'Okafor')),
    account(3, 'grace@example.com', teammate(3, 'Grace', 'Lindqvist'), 'TOKEN_REFRESH_FAILED'),
]

const ALL_ACCOUNTS = [
    account(1, 'john@example.com', {
        ...teammate(MOCK_DEFAULT_USER.id, 'John', 'Doe'),
        email: MOCK_DEFAULT_USER.email,
    }),
    ...TEAMMATE_ACCOUNTS,
]

type Story = StoryObj<MemberAccountsSectionProps>
const meta: Meta<MemberAccountsSectionProps> = {
    title: 'Scenes-App/Data Warehouse/Settings/Member accounts',
    component: MemberAccountsSection,
    args: {
        integrationKind: 'google-calendar',
        sourceLabel: 'Google Calendar',
    },
    parameters: {
        mockDate: '2026-10-06',
        viewMode: 'story',
        testOptions: {
            snapshotBrowsers: ['chromium'],
        },
    },
}

export default meta

export const NoAccountsConnected: Story = {
    decorators: [mswDecorator(integrationsMock([]))],
}

export const TeammatesConnected: Story = {
    decorators: [mswDecorator(integrationsMock(TEAMMATE_ACCOUNTS))],
}

export const OwnAccountConnected: Story = {
    decorators: [mswDecorator(integrationsMock(ALL_ACCOUNTS))],
}

// The scene is about this wide when the side panel is open on a laptop.
export const OwnAccountConnectedNarrow: Story = {
    decorators: [
        mswDecorator(integrationsMock(ALL_ACCOUNTS)),
        (StoryComponent) => (
            <div className="w-130">
                <StoryComponent />
            </div>
        ),
    ],
}
