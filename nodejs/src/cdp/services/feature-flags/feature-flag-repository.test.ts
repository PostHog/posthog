import { DateTime } from 'luxon'

import { closeHub, createHub } from '~/common/utils/db/hub'
import { createTestTeamFixture, insertRow } from '~/tests/helpers/sql'
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

            await insertFlag(teamId, 'old-project-two', {
                createdDaysAgo: 30,
                updatedDaysAgo: 20,
                filters: projectTwoOnly,
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

        it.each<[string, Partial<FeatureFlagListQuery>, string[]]>([
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
            ['limit', { limit: 1 }, ['new-for-everyone']],
        ])('returns %s', async (_name, query, expectedKeys) => {
            const result = await repository.list(teamId, { ...baseQuery, ...query })

            expect(result.keys).toEqual(expectedKeys)
            expect(result.count).toBe(expectedKeys.length)
        })
    })
})
