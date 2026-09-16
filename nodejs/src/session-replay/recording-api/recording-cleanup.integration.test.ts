import { randomUUID } from 'crypto'

import { defaultConfig } from '~/common/config/config'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { RecordingService } from './recording-service'
import { KeyStore, RecordingDecryptor } from './types'

// The unit tests assert the statement text against a mock, so a bad column, cast or CTE would pass
// them. These run the real SQL.
describe('recording cleanup (integration)', () => {
    let postgres: PostgresRouter
    let service: RecordingService
    let teamId: number
    let userId: number

    let scannerId: string
    let targetObservationId: string
    let otherObservationId: string
    let alertId: string

    beforeEach(async () => {
        scannerId = randomUUID()
        targetObservationId = randomUUID()
        otherObservationId = randomUUID()
        alertId = randomUUID()

        postgres = new PostgresRouter(defaultConfig)
        const fixture = await createTestTeamFixture(postgres)
        teamId = fixture.team.id
        userId = fixture.userId

        const keyStore = {
            deleteKey: jest
                .fn()
                .mockResolvedValue({ status: 'deleted', deletedAt: 1700000000, deletedBy: 'test@example.com' }),
        } as unknown as KeyStore

        service = new RecordingService(
            {} as never,
            'test-bucket',
            'session_recordings',
            keyStore,
            {} as unknown as RecordingDecryptor,
            undefined,
            undefined,
            postgres,
            undefined
        )

        await postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO replay_vision_replayscanner
                 (id, team_id, name, description, scanner_type, scanner_config, query, sampling_rate,
                  sampling_mode, provider, model, enabled, emits_signals, scanner_version, last_swept_at,
                  search_suggestions, admission_credits_since_refresh, created_at, updated_at)
             VALUES ($1, $2, 'cleanup-scanner', '', 'monitor', '{}'::jsonb, '{}'::jsonb, 1.0,
                     'comprehensive', 'google', 'gemini-3.8-flash', true, false, 1, now(),
                     '{}'::jsonb, 0, now(), now())`,
            [scannerId, teamId],
            'fixtureScanner'
        )

        for (const [observationId, sessionId] of [
            [targetObservationId, 'session-to-delete'],
            [otherObservationId, 'session-to-keep'],
        ]) {
            await postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO replay_vision_replayobservation
                     (id, scanner_id, team_id, session_id, status, error_reason, workflow_id,
                      scanner_snapshot, scanner_result, triggered_by, created_at, completed_at)
                 VALUES ($1, $2, $3, $4, 'succeeded', '', '', '{}'::jsonb, '{}'::jsonb, 'schedule', now(), now())`,
                [observationId, scannerId, teamId, sessionId],
                'fixtureObservation'
            )
        }

        await postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO replay_vision_replayobservationlabel
                 (id, observation_id, team_id, is_correct, feedback, created_at, updated_at)
             VALUES ($1, $2, $3, true, '', now(), now())`,
            [randomUUID(), targetObservationId, teamId],
            'fixtureLabel'
        )
        await postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO replay_vision_replayobservationview
                 (id, observation_id, team_id, user_id, created_at)
             VALUES ($1, $2, $3, $4, now())`,
            [randomUUID(), targetObservationId, teamId, userId],
            'fixtureView'
        )
        await postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO replay_vision_visionalertconfiguration
                 (id, scanner_id, team_id, name, enabled, kind, selection, metric, direction,
                  window_days, check_interval_minutes, state, consecutive_failures,
                  evaluation_periods, datapoints_to_alarm, cooldown_minutes, created_at, updated_at)
             VALUES ($1, $2, $3, 'cleanup-alert', true, 'match', '{}'::jsonb, 'count', 'above',
                     1, 60, 'not_firing', 0, 1, 1, 0, now(), now())`,
            [alertId, scannerId, teamId],
            'fixtureAlert'
        )
        await postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO replay_vision_visionalertmatch
                 (id, alert_id, observation_id, team_id, created_at)
             VALUES ($1, $2, $3, $4, now())`,
            [randomUUID(), alertId, targetObservationId, teamId],
            'fixtureMatch'
        )
        await postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_exportedasset
                 (team_id, export_format, created_at, export_context, is_system, expires_after)
             VALUES ($1, 'video/mp4', now(), $2::jsonb, true, now() + interval '30 days')`,
            [teamId, JSON.stringify({ session_recording_id: 'session-to-delete' })],
            'fixtureAsset'
        )
    })

    afterEach(async () => {
        await postgres.end()
    })

    const count = async (sql: string, params: unknown[]): Promise<number> => {
        const result = await postgres.query(PostgresUse.COMMON_READ, sql, params, 'assertion')
        return Number(result.rows[0].count)
    }

    it('removes the observation graph for the deleted recording and leaves the rest', async () => {
        await service.deleteRecordings(['session-to-delete'], teamId, 'test@example.com')

        expect(
            await count(`SELECT count(*) FROM replay_vision_replayobservation WHERE id = $1`, [targetObservationId])
        ).toBe(0)
        expect(
            await count(`SELECT count(*) FROM replay_vision_replayobservationlabel WHERE observation_id = $1`, [
                targetObservationId,
            ])
        ).toBe(0)
        expect(
            await count(`SELECT count(*) FROM replay_vision_replayobservationview WHERE observation_id = $1`, [
                targetObservationId,
            ])
        ).toBe(0)
        expect(
            await count(`SELECT count(*) FROM replay_vision_visionalertmatch WHERE observation_id = $1`, [
                targetObservationId,
            ])
        ).toBe(0)

        // An observation of a different recording is untouched.
        expect(
            await count(`SELECT count(*) FROM replay_vision_replayobservation WHERE id = $1`, [otherObservationId])
        ).toBe(1)
    })

    it('expires the rendered video for the deleted recording', async () => {
        await service.deleteRecordings(['session-to-delete'], teamId, 'test@example.com')

        expect(
            await count(
                `SELECT count(*) FROM posthog_exportedasset
                 WHERE team_id = $1 AND expires_after > now()`,
                [teamId]
            )
        ).toBe(0)
    })
})
