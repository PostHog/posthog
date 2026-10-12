import { DateTime } from 'luxon'

import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { createTestTeamFixture, getTeamMemberUserId, insertRow } from '~/tests/helpers/sql'
import { Hub } from '~/types'

import {
    FeatureFlagFilters,
    FeatureFlagListQuery,
    FeatureFlagRepository,
    FeatureFlagTargetingFilter,
    flagMatchesTargeting,
} from './feature-flag-repository'

const projectTwoOnly: FeatureFlagFilters = {
    groups: [{ properties: [{ key: 'project_id', value: ['2'], operator: 'exact' }], rollout_percentage: 100 }],
}

describe('FeatureFlagRepository', () => {
    describe('flagMatchesTargeting', () => {
        const only: FeatureFlagTargetingFilter = { property: 'project_id', value: '2', match: 'only' }
        const includes: FeatureFlagTargetingFilter = { ...only, match: 'includes' }

        it.each<[string, FeatureFlagFilters | null, FeatureFlagTargetingFilter, boolean]>([
            ['only, one condition for the value', projectTwoOnly, only, true],
            [
                'only, numeric value and missing operator',
                { groups: [{ properties: [{ key: 'project_id', value: 2 }], rollout_percentage: null }] },
                only,
                true,
            ],
            [
                'only, condition also lists another value',
                { groups: [{ properties: [{ key: 'project_id', value: ['2', '3'] }] }] },
                only,
                false,
            ],
            [
                'only, another condition releases to everyone',
                { groups: [...projectTwoOnly.groups!, { properties: [], rollout_percentage: 50 }] },
                only,
                false,
            ],
            [
                'only, another condition is at 0% rollout',
                { groups: [...projectTwoOnly.groups!, { properties: [], rollout_percentage: 0 }] },
                only,
                true,
            ],
            ['only, no conditions', { groups: [] }, only, false],
            ['only, filters missing', null, only, false],
            [
                'includes, condition also lists another value',
                { groups: [{ properties: [{ key: 'project_id', value: ['3', '2'] }] }] },
                includes,
                true,
            ],
            [
                'includes, non-exact operator',
                { groups: [{ properties: [{ key: 'project_id', value: '2', operator: 'icontains' }] }] },
                includes,
                false,
            ],
            [
                'includes, matching condition is at 0% rollout',
                { groups: [{ ...projectTwoOnly.groups![0], rollout_percentage: 0 }] },
                includes,
                false,
            ],
        ])('%s', (_name, filters, targeting, expected) => {
            expect(flagMatchesTargeting(filters, targeting)).toBe(expected)
        })
    })

    describe('list', () => {
        let hub: Hub
        let repository: FeatureFlagRepository
        let teamId: number
        let ownerId: number | null

        const baseQuery: FeatureFlagListQuery = {
            status: 'enabled',
            search: null,
            createdBefore: null,
            updatedBefore: null,
            targeting: null,
            limit: 25,
        }

        const insertFlag = async (
            team: number,
            key: string,
            overrides: { createdDaysAgo?: number; updatedDaysAgo?: number; filters?: FeatureFlagFilters } & Record<
                string,
                unknown
            > = {}
        ): Promise<void> => {
            const { createdDaysAgo = 0, updatedDaysAgo, filters = { groups: [] }, ...columns } = overrides
            const now = DateTime.utc()
            await insertRow(hub.postgres, 'posthog_featureflag', {
                key,
                name: `${key} name`,
                filters,
                active: true,
                deleted: false,
                team_id: team,
                created_at: now.minus({ days: createdDaysAgo }).toISO(),
                updated_at: now.minus({ days: updatedDaysAgo ?? createdDaysAgo }).toISO(),
                ...columns,
            })
        }

        beforeEach(async () => {
            hub = await createHub()
            repository = new FeatureFlagRepository(hub.postgres)
            teamId = (await createTestTeamFixture(hub.postgres)).team.id
            const otherTeamId = (await createTestTeamFixture(hub.postgres)).team.id

            ownerId = await getTeamMemberUserId(hub.postgres, teamId)

            await insertFlag(teamId, 'old-project-two', {
                createdDaysAgo: 30,
                updatedDaysAgo: 20,
                filters: projectTwoOnly,
                created_by_id: ownerId,
            })
            await insertFlag(teamId, 'old-recently-changed', { createdDaysAgo: 20, updatedDaysAgo: 1 })
            await insertFlag(teamId, 'new-for-everyone', { filters: { groups: [{ rollout_percentage: 100 }] } })
            await insertFlag(teamId, 'disabled-flag', { createdDaysAgo: 10, active: false })
            await insertFlag(teamId, 'deleted-flag', { createdDaysAgo: 10, deleted: true })
            await insertFlag(teamId, 'archived-flag', { createdDaysAgo: 10, active: false, archived: true })
            await insertFlag(otherTeamId, 'other-team-flag', { createdDaysAgo: 30, filters: projectTwoOnly })
        })

        afterEach(async () => {
            await closeHub(hub)
        })

        it.each<[string, Partial<FeatureFlagListQuery>, string[], boolean?]>([
            ['enabled flags by default', {}, ['new-for-everyone', 'old-recently-changed', 'old-project-two']],
            [
                'any status',
                { status: 'any' },
                ['new-for-everyone', 'disabled-flag', 'old-recently-changed', 'old-project-two'],
            ],
            ['disabled flags', { status: 'disabled' }, ['disabled-flag']],
            [
                'created more than a week ago',
                { createdBefore: DateTime.utc().minus({ days: 7 }).toJSDate() },
                ['old-recently-changed', 'old-project-two'],
            ],
            [
                'changed more than a week ago',
                { updatedBefore: DateTime.utc().minus({ days: 7 }).toJSDate() },
                ['old-project-two'],
            ],
            ['search with a LIKE wildcard in the text', { search: 'old_project' }, []],
            ['search by key or name', { search: 'PROJECT-TWO' }, ['old-project-two']],
            [
                'rolled out only to project 2',
                { targeting: { property: 'project_id', value: '2', match: 'only' } },
                ['old-project-two'],
            ],
            ['limit', { limit: 1 }, ['new-for-everyone'], true],
            [
                'limit equal to the matches',
                { limit: 3 },
                ['new-for-everyone', 'old-recently-changed', 'old-project-two'],
            ],
        ])('returns %s', async (_name, query, expectedKeys, expectedHasMore = false) => {
            const result = await repository.list(teamId, { ...baseQuery, ...query })

            expect(result).toMatchObject({ keys: expectedKeys, count: expectedKeys.length, has_more: expectedHasMore })
        })

        it('finds an old flag for the release condition behind more than 1000 newer flags', async () => {
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_featureflag (key, name, filters, active, deleted, team_id, created_at, updated_at)
                 SELECT 'newer-' || i, 'newer', $2::jsonb, TRUE, FALSE, $1, now() - interval '1 day', now() - interval '1 day'
                 FROM generate_series(1, 1000) AS i`,
                [
                    teamId,
                    JSON.stringify({
                        groups: [{ properties: [{ key: 'email', value: ['a@example.com'] }], rollout_percentage: 100 }],
                    }),
                ],
                'insertNewerFlags'
            )

            const result = await repository.list(teamId, {
                ...baseQuery,
                targeting: { property: 'project_id', value: '2', match: 'only' },
            })

            expect(result.keys).toEqual(['old-project-two'])
        })

        it('returns the flag creator email', async () => {
            const ownerEmail = (
                await hub.postgres.query(
                    PostgresUse.COMMON_READ,
                    'SELECT email FROM posthog_user WHERE id = $1',
                    [ownerId],
                    'getOwnerEmail'
                )
            ).rows[0].email

            const result = await repository.list(teamId, { ...baseQuery, search: 'old' })

            expect(result.flags.map((flag) => [flag.key, flag.created_by_email])).toEqual([
                ['old-recently-changed', null],
                ['old-project-two', ownerEmail],
            ])
        })
    })
})
