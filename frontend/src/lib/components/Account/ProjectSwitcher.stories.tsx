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

const LOOKBACK_DAYS = 30

// Relative to now so the rendered durations stay stable as real time passes.
const daysAgo = (days: number): string => dayjs().subtract(days, 'day').toISOString()

/**
 * `days` is capped at the lookback window on purpose: every probe is bounded to it, so the API
 * cannot report a `last_data_at` older than that. Anything further back arrives as null, which
 * is what `null` means here.
 */
const project = (
    teamId: number,
    freshness: string,
    days: number | null,
    sources: [string, number][] = []
): Record<string, unknown> => ({
    team_id: teamId,
    freshness,
    last_data_at: days === null ? null : daysAgo(days),
    sources: sources.map(([data_source, sourceDays]) => ({ data_source, last_data_at: daysAgo(sourceDays) })),
})

const DATA_FRESHNESS = {
    lookback_days: LOOKBACK_DAYS,
    quiet_after_days: 7,
    results: [
        project(MOCK_DEFAULT_TEAM.id, 'live', 0, [
            ['product_analytics', 0],
            ['session_replay', 0],
        ]),
        project(1001, 'stale', 12, [['product_analytics', 12]]),
        // Last saw data before the lookback window, so all we can say is "over 30 days".
        project(1002, 'stale', null),
        project(1003, 'never', null),
        project(1004, 'stale', null),
        // Still in use, just not the project you're currently in.
        project(1005, 'live', 0, [
            ['product_analytics', 0],
            ['logs', 1],
        ]),
        project(1006, 'stale', 26, [['session_replay', 26]]),
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
                [`/api/organizations/${MOCK_DEFAULT_ORGANIZATION.id}/teams/data_freshness/`]: () => [
                    200,
                    DATA_FRESHNESS,
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
