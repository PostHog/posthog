import { Client } from 'pg'

import { createExampleInvocation } from '~/cdp/_tests/fixtures'
import { HogFlowAction } from '~/cdp/schema/hogflow'
import { defaultConfig } from '~/common/config/config'
import { RedisV2 } from '~/common/redis/redis-v2'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { UUIDT } from '~/common/utils/utils'
import { waitForExpect } from '~/tests/helpers/expectations'
import { createTestTeamFixture } from '~/tests/helpers/sql'
import { Hub } from '~/types'

import { MessageOptOutRecord } from '../../../types'
import { RecipientsManagerService } from '../../managers/recipients-manager.service'
import { TeamWorkflowsConfigService } from '../../managers/team-workflows-config.service'
import { EmailSuppressionService } from '../email-suppression.service'
import { createFrequencyCapValkeyPool } from '../frequency-cap-valkey-pool'
import { FrequencyCapCheck, RecipientPreferencesService } from '../recipient-preferences.service'
import {
    MAX_RUNNING_FREQUENCY_CAP_CHECKS,
    SandboxRecipientCheckDependencies,
    SandboxRecipientCheckRequest,
    checkSandboxRecipient,
    sandboxRecipientReads,
} from './sandbox-recipient-checks'

describe('checkSandboxRecipient', () => {
    let hub: Hub
    let valkey: RedisV2
    let postgres: PostgresRouter
    let unreachable: PostgresRouter
    let suppressionList: EmailSuppressionService
    let reads: SandboxRecipientCheckDependencies
    let teamId: number
    let address: string
    let frequencyCap: () => Promise<FrequencyCapCheck>
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
            frequencyCap,
            ...request,
        })

    const marketingEmail: Extract<HogFlowAction, { type: 'function_email' }> = {
        id: 'email',
        name: 'Send email',
        description: '',
        type: 'function_email',
        filters: null,
        config: { template_id: 'template-email', message_category_type: 'marketing', inputs: {} },
        created_at: 0,
        updated_at: 0,
    }

    const realFrequencyCap = (configReader: PostgresRouter = postgres): (() => Promise<FrequencyCapCheck>) => {
        const preferences = new RecipientPreferencesService(
            new RecipientsManagerService(postgres),
            new EmailSuppressionService(postgres, suppressionConfig),
            {
                teamWorkflowsConfig: new TeamWorkflowsConfigService(configReader, hub.pubSub),
                valkey,
                persons: {
                    getCyclotronPerson: () => Promise.reject(new Error('an email cap check reads the run person')),
                },
            }
        )
        return () => preferences.checkFrequencyCap(createExampleInvocation({ team_id: teamId }), marketingEmail)
    }

    const capThePerson = async (): Promise<void> => {
        await postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO workflows_teamworkflowsconfig
                (team_id, capture_workflows_engagement_events, email_tracking_consent_mode,
                 email_sending_suspension_reason, marketing_frequency_cap_max_messages,
                 marketing_frequency_cap_window_days)
             VALUES ($1, false, 'off', '', 1, 7)`,
            [teamId],
            'test:cap-one-marketing-email-a-week'
        )
        expect(await frequencyCap()).toEqual({ capped: false })
    }

    const storePreferences = (preferences: Record<string, string>) =>
        postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_messagerecipientpreference (id, team_id, identifier, preferences, created_at, updated_at, deleted)
             VALUES ($1, $2, $3, $4, NOW(), NOW(), false)`,
            [new UUIDT().toString(), teamId, address, JSON.stringify(preferences)],
            'test:store-recipient-preferences'
        )

    beforeAll(async () => {
        hub = await createHub()
        valkey = createFrequencyCapValkeyPool(defaultConfig)!
        postgres = new PostgresRouter(defaultConfig)
        unreachable = new PostgresRouter({
            ...defaultConfig,
            DATABASE_URL: 'postgres://posthog:posthog@127.0.0.1:1/posthog',
            DATABASE_READONLY_URL: '',
        })
    })

    afterAll(async () => {
        await Promise.all([postgres.end(), unreachable.end(), closeHub(hub)])
    })

    beforeEach(async () => {
        teamId = (await createTestTeamFixture(postgres)).team.id
        address = `member-${teamId}@example.com`
        suppressionList = new EmailSuppressionService(postgres, suppressionConfig)
        reads = sandboxRecipientReads(postgres, suppressionConfig)
        frequencyCap = realFrequencyCap()
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
        ['a person at the marketing frequency cap', capThePerson, {}, 'frequency_capped'],
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
        [
            'the suppression lookup',
            'posthog_messagesuppression',
            (onePool: SandboxRecipientCheckDependencies) =>
                onePool.recipients.get({ teamId, identifier: address }).then(() => 'answered'),
        ],
        [
            'the opt-out lookup',
            'posthog_messagerecipientpreference',
            (onePool: SandboxRecipientCheckDependencies) =>
                onePool.suppression.isSuppressed(teamId, address, { transactional: false }).then(() => 'answered'),
        ],
    ])(
        'blocks for a retry when %s waits behind a lock past the deadline, and frees its pooled connection',
        async (_case, table, readTheOtherTable) => {
            const reader = new PostgresRouter({
                ...defaultConfig,
                DATABASE_READONLY_URL: '',
                POSTGRES_CONNECTION_POOL_SIZE: 1,
            })
            const lockHolder = new Client({ connectionString: defaultConfig.DATABASE_URL })
            lockHolder.on('error', () => undefined)
            await lockHolder.connect()
            try {
                await lockHolder.query('BEGIN')
                await lockHolder.query(`SET LOCAL idle_in_transaction_session_timeout = '10s'`)
                await lockHolder.query(`LOCK TABLE ${table} IN ACCESS EXCLUSIVE MODE`)
                reads = sandboxRecipientReads(reader, suppressionConfig, 200)

                expect(await check()).toEqual({ ok: false, reason: 'authorization_unavailable' })
                expect(await readTheOtherTable(sandboxRecipientReads(reader, suppressionConfig, 1_000))).toBe(
                    'answered'
                )
            } finally {
                await lockHolder.end()
                await reader.end()
            }
        }
    )

    it('lets sends through when the cap check throws, and still caps after more failures than there are check slots', async () => {
        const throwing = (): Promise<FrequencyCapCheck> => {
            throw new Error('frequency cap store is down')
        }
        for (let attempt = 0; attempt <= MAX_RUNNING_FREQUENCY_CAP_CHECKS; attempt++) {
            expect(await check({ frequencyCap: throwing })).toEqual({ ok: true })
        }

        await capThePerson()
        expect(await check()).toEqual({ ok: false, reason: 'frequency_capped' })
    })

    it('caps every concurrent send to a capped person, however many run at once', async () => {
        await capThePerson()
        const sends = Array.from({ length: MAX_RUNNING_FREQUENCY_CAP_CHECKS + 2 }, () => check())

        expect(await Promise.all(sends)).toEqual(sends.map(() => ({ ok: false, reason: 'frequency_capped' })))
    })

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
        ['the frequency cap on a test send', capThePerson, { isTest: true }],
        ['the frequency cap on a transactional step', capThePerson, { categoryType: 'transactional' }],
    ])('lets through %s', async (_case, arrange, request) => {
        await arrange()
        expect(await check(request)).toEqual({ ok: true })
    })

    describe('with the marketing frequency cap read behind a lock', () => {
        let lockHolder: Client

        beforeEach(async () => {
            await capThePerson()
            expect(await check()).toEqual({ ok: false, reason: 'frequency_capped' })

            lockHolder = new Client({ connectionString: defaultConfig.DATABASE_URL })
            lockHolder.on('error', () => undefined)
            await lockHolder.connect()
            await lockHolder.query('BEGIN')
            await lockHolder.query(`SET LOCAL idle_in_transaction_session_timeout = '10s'`)
            await lockHolder.query('LOCK TABLE workflows_teamworkflowsconfig IN ACCESS EXCLUSIVE MODE')
            reads = sandboxRecipientReads(postgres, suppressionConfig, 200)
        })

        afterEach(async () => {
            await lockHolder.end()
        })

        it('lets the send through once the cap check passes its deadline', async () => {
            expect(await check({ frequencyCap: realFrequencyCap() })).toEqual({ ok: true })
        })

        it('keeps recipient reads on a shared pool working while a stalled cap store holds its checks, and caps again once they finish', async () => {
            const shared = new PostgresRouter({
                ...defaultConfig,
                DATABASE_READONLY_URL: '',
                POSTGRES_CONNECTION_POOL_SIZE: MAX_RUNNING_FREQUENCY_CAP_CHECKS + 2,
            })
            let gaveUp: NodeJS.Timeout | undefined
            try {
                reads = sandboxRecipientReads(shared, suppressionConfig, 200)
                const stalled = Array.from({ length: MAX_RUNNING_FREQUENCY_CAP_CHECKS + 4 }, () =>
                    check({ frequencyCap: realFrequencyCap(shared) })
                )
                expect(await Promise.all(stalled)).toEqual(stalled.map(() => ({ ok: true })))
                expect(
                    await Promise.race([
                        new RecipientsManagerService(shared)
                            .get({ teamId, identifier: `uncached-${teamId}@example.com` })
                            .then(() => 'answered'),
                        new Promise((resolve) => {
                            gaveUp = setTimeout(() => resolve('still waiting for a connection'), 3_000)
                        }),
                    ])
                ).toBe('answered')

                await lockHolder.query('COMMIT')
                await waitForExpect(async () => {
                    expect(await check()).toEqual({ ok: false, reason: 'frequency_capped' })
                }, 3_000)
            } finally {
                clearTimeout(gaveUp)
                await shared.end()
            }
        })
    })
})
