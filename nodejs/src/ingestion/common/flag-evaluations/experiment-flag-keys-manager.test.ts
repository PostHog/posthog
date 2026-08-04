import { defaultConfig } from '~/common/config/config'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { commonOrganizationId, createTeam, insertRow, resetTestDatabase } from '~/tests/helpers/sql'

import { ExperimentFlagKeysManager, createExperimentFlagKeysManager } from './experiment-flag-keys-manager'

describe('ExperimentFlagKeysManager', () => {
    let postgres: PostgresRouter
    let manager: ExperimentFlagKeysManager
    let teamId: number

    const insertFeatureFlag = async (team: number, key: string, deleted = false): Promise<number> => {
        const row = await insertRow(postgres, 'posthog_featureflag', {
            key,
            name: '',
            filters: '{}',
            created_at: new Date().toISOString(),
            deleted,
            active: true,
            archived: false,
            team_id: team,
        })
        return row.id
    }

    const insertExperiment = async (
        team: number,
        featureFlagId: number,
        deleted: boolean | null = false
    ): Promise<void> => {
        await insertRow(postgres, 'posthog_experiment', {
            name: 'Test experiment',
            filters: '{}',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            archived: false,
            feature_flag_id: featureFlagId,
            team_id: team,
            deleted,
            only_count_matured_users: false,
            feature_flag_auto_archived: false,
        })
    }

    // The manager exposes batched per-team sets; these tests are about one flag at a time.
    const hasExperimentFlag = async (team: number, key: string): Promise<boolean> =>
        (await manager.getExperimentFlagKeys([team]))[String(team)]?.has(key) ?? false

    // Every test creates its own team and scopes its assertions to it, so one reset is
    // enough; the manager is rebuilt per test so no cached set survives either.
    beforeAll(async () => {
        await resetTestDatabase()
    })

    beforeEach(async () => {
        postgres = new PostgresRouter(defaultConfig)
        manager = new ExperimentFlagKeysManager(postgres)
        teamId = await createTeam(postgres, commonOrganizationId)
    })

    afterEach(async () => {
        await postgres.end()
    })

    it.each([
        ['returns true when a live experiment backs the flag', false, false, true],
        ['returns false when the experiment linking the flag is deleted', false, true, false],
        // deleted is nullable, and `= false` excludes NULL. Rewriting the predicate as
        // `IS NOT TRUE` would flip this without any other case noticing.
        ['returns false when the experiment deleted state is null', false, null, false],
        ['returns false when the feature flag itself is deleted', true, false, false],
    ])('%s', async (_case, flagDeleted, experimentDeleted, expected) => {
        const flagId = await insertFeatureFlag(teamId, 'my-experiment-flag', flagDeleted)
        await insertExperiment(teamId, flagId, experimentDeleted)

        const result = await hasExperimentFlag(teamId, 'my-experiment-flag')

        expect(result).toBe(expected)
    })

    it('returns false for a team with no experiments at all', async () => {
        const result = await hasExperimentFlag(teamId, 'nonexistent-flag')

        expect(result).toBe(false)
    })

    it("does not leak another team's experiment flag key", async () => {
        const otherTeamId = await createTeam(postgres, commonOrganizationId)
        const flagId = await insertFeatureFlag(otherTeamId, 'shared-key-name')
        await insertExperiment(otherTeamId, flagId)

        const result = await hasExperimentFlag(teamId, 'shared-key-name')

        expect(result).toBe(false)
    })

    // The experiments API can't build this pair today, since it resolves flags by key
    // within the team. Scoping on the experiment's team instead would answer for the
    // wrong team here, and the routing fork looks up by the event's team and flag key.
    it("files the key under the flag's team, not the experiment's", async () => {
        const otherTeamId = await createTeam(postgres, commonOrganizationId)
        const flagId = await insertFeatureFlag(teamId, 'cross-team-flag')
        await insertExperiment(otherTeamId, flagId)

        expect(await hasExperimentFlag(teamId, 'cross-team-flag')).toBe(true)
        expect(await hasExperimentFlag(otherTeamId, 'cross-team-flag')).toBe(false)
    })

    // Drives the loader's response shape directly, so it uses a stub router rather than
    // the rows inserted above.
    it('keeps every experiment-backed key for a team, not just the last', async () => {
        const stubbed = new ExperimentFlagKeysManager({
            query: jest.fn().mockResolvedValue({
                rows: [
                    { team_id: 1, key: 'flag-a' },
                    { team_id: 1, key: 'flag-b' },
                    { team_id: 2, key: 'flag-c' },
                ],
            }),
        } as unknown as PostgresRouter)

        const keys = await stubbed.getExperimentFlagKeys([1, 2])

        expect(keys['1']).toEqual(new Set(['flag-a', 'flag-b']))
        expect(keys['2']).toEqual(new Set(['flag-c']))
    })

    describe('createExperimentFlagKeysManager', () => {
        it.each([
            [true, true],
            [false, false],
        ])('measurement enabled %s builds a manager: %s', (enabled, expected) => {
            const created = createExperimentFlagKeysManager({} as PostgresRouter, {
                EXPERIMENT_FLAG_KEYS_MEASUREMENT_ENABLED: enabled,
            })

            expect(created !== undefined).toBe(expected)
        })
    })
})
