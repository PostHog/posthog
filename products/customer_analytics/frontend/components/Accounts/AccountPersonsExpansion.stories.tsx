import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'

import type {
    AccountPersonApi,
    AccountPersonsResponseApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { AccountViewComponent } from './AccountViewComponent'
import type { AccountViewTileConfig } from './accountViewTileConfig'

const PERSONS_URL = '/api/projects/:team_id/accounts/:account_id/persons/'

const PEOPLE: AccountPersonApi[] = [
    {
        id: '0192b5a0-0000-7000-8000-000000000001',
        name: 'Ada Lovelace',
        distinct_ids: ['ada@example.com'],
        properties: { email: 'ada@example.com', plan: 'enterprise' },
        account_first_seen: '2026-04-30T09:12:00Z',
        account_last_seen: '2026-05-20T16:40:00Z',
    },
    {
        // Older than 90 days: still listed because membership covers all history.
        id: '0192b5a0-0000-7000-8000-000000000002',
        name: 'Grace Hopper',
        distinct_ids: ['grace@example.com'],
        properties: { email: 'grace@example.com', plan: 'team' },
        account_first_seen: '2025-11-02T08:00:00Z',
        account_last_seen: '2026-01-15T11:05:00Z',
    },
    {
        // No email: cannot be selected for copy.
        id: '0192b5a0-0000-7000-8000-000000000003',
        name: '0192b5a0-0000-7000-8000-000000000003',
        distinct_ids: ['anon-4f1c'],
        properties: {},
        account_first_seen: '2026-05-01T13:30:00Z',
        account_last_seen: '2026-05-01T13:31:00Z',
    },
]

type ListState = 'loaded' | 'loading' | 'empty' | 'failed'

interface AccountUsersStoryProps {
    state?: ListState
    hasMore?: boolean
    narrow?: boolean
    initialConfig?: AccountViewTileConfig
}

function AccountUsersStory({
    state = 'loaded',
    hasMore = false,
    narrow,
    initialConfig,
}: AccountUsersStoryProps): JSX.Element {
    useStorybookMocks({
        get: {
            [PERSONS_URL]: (): Promise<never> | [number, unknown] | AccountPersonsResponseApi => {
                if (state === 'loading') {
                    return new Promise<never>(() => {})
                }
                if (state === 'failed') {
                    return [500, { detail: 'Could not load people.' }]
                }
                return {
                    results: state === 'empty' ? [] : PEOPLE,
                    limit: 20,
                    offset: 0,
                    has_more: hasMore,
                }
            },
        },
    })

    return (
        // About the scene width left when the side panel is open. The narrow story pins it so a regression shows up.
        <div className={narrow ? 'w-[520px] p-4' : 'w-[1000px] p-4'}>
            <AccountViewComponent
                kind="users"
                accountId="account-1"
                externalId="acme"
                initialConfig={initialConfig}
                embedded={false}
            />
        </div>
    )
}

const meta: Meta<typeof AccountUsersStory> = {
    title: 'Customer analytics/Account users',
    component: AccountUsersStory,
    parameters: {
        layout: 'padded',
        mockDate: '2026-05-21',
        // The Users tab picks its read source from this flag.
        featureFlags: [FEATURE_FLAGS.CUSTOMER_ANALYTICS, FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_PERSONS_UI],
    },
}
export default meta

type Story = StoryObj<typeof AccountUsersStory>

export const Loaded: Story = { args: { hasMore: true } }

export const LoadedNarrow: Story = { args: { hasMore: true, narrow: true } }

export const WithPropertyColumn: Story = {
    args: { initialConfig: { propertyColumns: ['plan'], sorting: { columnKey: 'property:plan', order: 1 } } },
}

export const WithPropertyColumnNarrow: Story = {
    args: { narrow: true, initialConfig: { propertyColumns: ['plan'] } },
}

export const Loading: Story = {
    args: { state: 'loading' },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

export const Empty: Story = { args: { state: 'empty' } }

export const FilteredEmpty: Story = { args: { state: 'empty', initialConfig: { searchTerm: 'nobody' } } }

export const FilteredEmptyNarrow: Story = {
    args: { state: 'empty', narrow: true, initialConfig: { searchTerm: 'nobody' } },
}

export const LoadFailed: Story = { args: { state: 'failed' } }

export const LoadFailedNarrow: Story = { args: { state: 'failed', narrow: true } }
