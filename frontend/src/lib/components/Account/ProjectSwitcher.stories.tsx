import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { useStorybookMocks } from '~/mocks/browser'

import { ProjectSwitcher } from './ProjectSwitcher'

type StoryProps = { hasPendingInvite: boolean; hasDataFreshness?: boolean }

const PENDING_INVITE = {
    id: '018f0000-0000-0000-0000-000000000001',
    target_email: MOCK_DEFAULT_USER.email,
    organization_id: '018f0000-0000-0000-0000-00000000abcd',
    organization_name: 'Acme Corp',
    created_at: '2026-04-17T12:00:00Z',
}

// The case this feature exists for: a pile of similarly named leftovers around one product,
// where only one is real and the names alone can't tell you which.
const FRESHNESS_TEAMS = [
    { ...MOCK_DEFAULT_TEAM, id: 1001, project_id: 1001, name: 'MockHog staging' },
    { ...MOCK_DEFAULT_TEAM, id: 1002, project_id: 1002, name: 'MockHog test' },
    { ...MOCK_DEFAULT_TEAM, id: 1003, project_id: 1003, name: 'MockHog test 2' },
    { ...MOCK_DEFAULT_TEAM, id: 1004, project_id: 1004, name: 'MockHog dev sandbox' },
    { ...MOCK_DEFAULT_TEAM, id: 1005, project_id: 1005, name: 'MockHog EU' },
    { ...MOCK_DEFAULT_TEAM, id: 1006, project_id: 1006, name: 'MockHog old app' },
]

// Relative to now so the rendered durations stay stable as real time passes.
const daysAgo = (days: number): string => dayjs().subtract(days, 'day').toISOString()

const DATA_FRESHNESS = {
    lookback_days: 30,
    quiet_after_days: 7,
    results: [
        {
            team_id: MOCK_DEFAULT_TEAM.id,
            freshness: 'live',
            last_data_at: daysAgo(0),
            sources: [
                { data_source: 'product_analytics', last_data_at: daysAgo(0) },
                { data_source: 'session_replay', last_data_at: daysAgo(0) },
            ],
        },
        {
            team_id: 1001,
            freshness: 'stale',
            last_data_at: daysAgo(12),
            sources: [{ data_source: 'product_analytics', last_data_at: daysAgo(12) }],
        },
        {
            team_id: 1002,
            freshness: 'stale',
            last_data_at: daysAgo(96),
            sources: [{ data_source: 'product_analytics', last_data_at: daysAgo(96) }],
        },
        { team_id: 1003, freshness: 'never', last_data_at: null, sources: [] },
        {
            team_id: 1004,
            freshness: 'stale',
            last_data_at: daysAgo(410),
            sources: [{ data_source: 'error_tracking', last_data_at: daysAgo(410) }],
        },
        {
            // Still in use, just not the project you're currently in.
            team_id: 1005,
            freshness: 'live',
            last_data_at: daysAgo(0),
            sources: [
                { data_source: 'product_analytics', last_data_at: daysAgo(0) },
                { data_source: 'logs', last_data_at: daysAgo(1) },
            ],
        },
        {
            team_id: 1006,
            freshness: 'stale',
            last_data_at: daysAgo(200),
            sources: [{ data_source: 'session_replay', last_data_at: daysAgo(200) }],
        },
    ],
}

const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Components/Account/Project Switcher',
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
    render: ({ hasPendingInvite, hasDataFreshness }: StoryProps) => {
        const organization = hasDataFreshness
            ? { ...MOCK_DEFAULT_ORGANIZATION, teams: [MOCK_DEFAULT_TEAM, ...FRESHNESS_TEAMS] }
            : MOCK_DEFAULT_ORGANIZATION

        useStorybookMocks({
            get: {
                '/api/users/@me/': () => [
                    200,
                    {
                        ...MOCK_DEFAULT_USER,
                        organization,
                        pending_invites: hasPendingInvite ? [PENDING_INVITE] : [],
                    },
                ],
                '/api/organizations/@current/': () => [200, organization],
                '/api/environments/@current/': () => [200, MOCK_DEFAULT_TEAM],
                '/api/projects/@current/': () => [200, MOCK_DEFAULT_TEAM],
                [`/api/organizations/${MOCK_DEFAULT_ORGANIZATION.id}/data_freshness/`]: () => [
                    200,
                    hasDataFreshness ? DATA_FRESHNESS : { ...DATA_FRESHNESS, results: [] },
                ],
            },
        })

        return (
            <div className="w-[340px] border border-primary rounded bg-surface-primary">
                <ProjectSwitcher dialog />
            </div>
        )
    },
}
export default meta

type Story = StoryObj<(props: StoryProps) => JSX.Element>

export const NoPendingInvite: Story = {
    args: { hasPendingInvite: false },
}

export const WithPendingInvite: Story = {
    args: { hasPendingInvite: true },
}

export const WithDataFreshness: Story = {
    args: { hasPendingInvite: false, hasDataFreshness: true },
}
