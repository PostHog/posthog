import { Client } from 'pg'

import { defaultConfig } from '~/common/config/config'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { UUIDT } from '~/common/utils/utils'
import { waitForExpect } from '~/tests/helpers/expectations'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { MessageOptOutRecord } from '../../../types'
import { EmailSuppressionService } from '../email-suppression.service'
import { FrequencyCapCheck } from '../recipient-preferences.service'
import {
    SandboxRecipientCheckDependencies,
    SandboxRecipientCheckRequest,
    checkSandboxRecipient,
    sandboxRecipientReads,
} from './sandbox-recipient-checks'

describe('checkSandboxRecipient', () => {
    let postgres: PostgresRouter
    let unreachable: PostgresRouter
    let suppressionList: EmailSuppressionService
    let reads: SandboxRecipientCheckDependencies
    let teamId: number
    let address: string
    let frequencyCap: FrequencyCapCheck
    let optOuts: MessageOptOutRecord[]

    const suppressionConfig = { transientBounceThreshold: 5 }

    const check = (request: Partial<SandboxRecipientCheckRequest> = {}) =>
        checkSandboxRecipient(reads, {
            teamId,
            address,
            categoryId: 'newsletter',
            categoryType: 'marketing',
            optOuts,
            isTest: false,
            frequencyCap: () => Promise.resolve(frequencyCap),
            ...request,
        })

    const storePreferences = (preferences: Record<string, string>) =>
        postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_messagerecipientpreference (id, team_id, identifier, preferences, created_at, updated_at, deleted)
             VALUES ($1, $2, $3, $4, NOW(), NOW(), false)`,
            [new UUIDT().toString(), teamId, address, JSON.stringify(preferences)],
            'test:store-recipient-preferences'
        )

    beforeAll(() => {
        postgres = new PostgresRouter(defaultConfig)
        unreachable = new PostgresRouter({
            ...defaultConfig,
            DATABASE_URL: 'postgres://posthog:posthog@127.0.0.1:1/posthog',
            DATABASE_READONLY_URL: '',
        })
    })

    afterAll(async () => {
        await Promise.all([postgres.end(), unreachable.end()])
    })

    beforeEach(async () => {
        teamId = (await createTestTeamFixture(postgres)).team.id
        address = `member-${teamId}@example.com`
        suppressionList = new EmailSuppressionService(postgres, suppressionConfig)
        reads = sandboxRecipientReads(postgres, suppressionConfig)
        frequencyCap = { capped: false }
        optOuts = []
    })

    it('admits a recipient with no suppression, opt-out, or cap', async () => {
        expect(await check()).toEqual({ ok: true })
    })

    it.each<[string, () => unknown, Partial<SandboxRecipientCheckRequest>, string]>([
        ['a suppressed address', () => suppressionList.recordComplaints(teamId, [address], 'abuse'), {}, 'suppressed'],
        [
            'a hard-bounced address on a transactional step',
            () => suppressionList.recordHardBounces(teamId, [address], 'mailbox does not exist'),
            { categoryType: 'transactional' },
            'suppressed',
        ],
        [
            'a suppressed address on a test send',
            () => suppressionList.recordComplaints(teamId, [address], 'abuse'),
            { isTest: true },
            'suppressed',
        ],
        ['an opt-out from the category', () => storePreferences({ newsletter: 'OPTED_OUT' }), {}, 'opted_out'],
        ['an opt-out from all marketing', () => storePreferences({ $all: 'OPTED_OUT' }), {}, 'opted_out'],
        [
            'an opt-out recorded earlier in the run',
            () => (optOuts = [{ identifier: address, categoryId: '$all' } as MessageOptOutRecord]),
            {},
            'opted_out',
        ],
        [
            'a person at the marketing frequency cap',
            () => (frequencyCap = { capped: true, nextSlotAt: 0, holdHours: 4 }),
            {},
            'frequency_capped',
        ],
    ])('refuses %s', async (_case, arrange, request, reason) => {
        await arrange()
        expect(await check(request)).toEqual({ ok: false, reason })
    })

    it.each<[string, () => unknown, Partial<SandboxRecipientCheckRequest>]>([
        [
            'the opt-out lookup',
            () => (reads = { ...reads, recipients: sandboxRecipientReads(unreachable, suppressionConfig).recipients }),
            {},
        ],
        ['the suppression lookup', () => (reads = sandboxRecipientReads(unreachable, suppressionConfig)), {}],
        [
            'the suppression lookup on a transactional step',
            () => (reads = sandboxRecipientReads(unreachable, suppressionConfig)),
            { categoryType: 'transactional' },
        ],
    ])('blocks for a retry when %s fails', async (_case, arrange, request) => {
        arrange()
        expect(await check(request)).toEqual({ ok: false, reason: 'authorization_unavailable' })
    })

    it.each([
        ['the suppression lookup', 'posthog_messagesuppression'],
        ['the opt-out lookup', 'posthog_messagerecipientpreference'],
    ])(
        'blocks for a retry when %s waits behind a lock past the deadline, and gives its connection back',
        async (_case, table) => {
            const applicationName = `sandbox-recipient-reads-${teamId}`
            const reader = new PostgresRouter(defaultConfig, applicationName)
            const lockHolder = new Client({ connectionString: defaultConfig.DATABASE_URL })
            lockHolder.on('error', () => undefined)
            await lockHolder.connect()
            try {
                await lockHolder.query('BEGIN')
                await lockHolder.query(`SET LOCAL idle_in_transaction_session_timeout = '10s'`)
                await lockHolder.query(`LOCK TABLE ${table} IN ACCESS EXCLUSIVE MODE`)
                reads = sandboxRecipientReads(reader, suppressionConfig, 200)

                expect(await check()).toEqual({ ok: false, reason: 'authorization_unavailable' })
                await waitForExpect(async () => {
                    const { rows } = await postgres.query(
                        PostgresUse.COMMON_READ,
                        `SELECT count(*)::int AS waiting FROM pg_stat_activity
                         WHERE application_name = $1 AND wait_event_type = 'Lock'`,
                        [applicationName],
                        'test:sandbox-reads-waiting-on-lock'
                    )
                    expect(rows).toEqual([{ waiting: 0 }])
                }, 3_000)
            } finally {
                await lockHolder.end()
                await reader.end()
            }
        }
    )

    it.each<[string, () => unknown, Partial<SandboxRecipientCheckRequest>]>([
        [
            'a complaint on a transactional step',
            () => suppressionList.recordComplaints(teamId, [address], 'abuse'),
            { categoryType: 'transactional' },
        ],
        [
            'an opt-out on a transactional step',
            () => storePreferences({ $all: 'OPTED_OUT' }),
            { categoryType: 'transactional' },
        ],
        [
            'the frequency cap on a test send',
            () => (frequencyCap = { capped: true, nextSlotAt: 0, holdHours: null }),
            { isTest: true },
        ],
        [
            'the frequency cap on a transactional step',
            () => (frequencyCap = { capped: true, nextSlotAt: 0, holdHours: null }),
            { categoryType: 'transactional' },
        ],
    ])('lets through %s', async (_case, arrange, request) => {
        await arrange()
        expect(await check(request)).toEqual({ ok: true })
    })
})
