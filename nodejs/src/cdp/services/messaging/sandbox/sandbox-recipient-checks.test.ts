import { defaultConfig } from '~/common/config/config'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { UUIDT } from '~/common/utils/utils'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { MessageOptOutRecord } from '../../../types'
import { RecipientsManagerService } from '../../managers/recipients-manager.service'
import { EmailSuppressionService } from '../email-suppression.service'
import { FrequencyCapCheck } from '../recipient-preferences.service'
import { SandboxRecipientCheckRequest, checkSandboxRecipient } from './sandbox-recipient-checks'

describe('checkSandboxRecipient', () => {
    let postgres: PostgresRouter
    let suppression: EmailSuppressionService
    let recipients: RecipientsManagerService
    let teamId: number
    let address: string
    let frequencyCap: FrequencyCapCheck
    let optOuts: MessageOptOutRecord[]

    const check = (request: Partial<SandboxRecipientCheckRequest> = {}) =>
        checkSandboxRecipient(
            { suppression, recipients },
            {
                teamId,
                address,
                categoryId: 'newsletter',
                categoryType: 'marketing',
                optOuts,
                isTest: false,
                frequencyCap: () => Promise.resolve(frequencyCap),
                ...request,
            }
        )

    const storePreferences = (preferences: Record<string, string>) =>
        postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_messagerecipientpreference (id, team_id, identifier, preferences, created_at, updated_at, deleted)
             VALUES ($1, $2, $3, $4, NOW(), NOW(), false)`,
            [new UUIDT().toString(), teamId, address, JSON.stringify(preferences)],
            'test:store-recipient-preferences'
        )

    const failQuery = (tag: string) => {
        const realQuery = postgres.query.bind(postgres)
        jest.spyOn(postgres, 'query').mockImplementation(((...args: Parameters<typeof realQuery>) =>
            args[3] === tag ? Promise.reject(new Error('connection lost')) : realQuery(...args)) as typeof realQuery)
    }

    beforeAll(() => {
        postgres = new PostgresRouter(defaultConfig)
    })

    afterAll(async () => {
        await postgres.end()
    })

    beforeEach(async () => {
        teamId = (await createTestTeamFixture(postgres)).team.id
        address = `member-${teamId}@example.com`
        suppression = new EmailSuppressionService(postgres, { transientBounceThreshold: 5 })
        recipients = new RecipientsManagerService(postgres)
        frequencyCap = { capped: false }
        optOuts = []
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('admits a recipient with no suppression, opt-out, or cap', async () => {
        expect(await check()).toEqual({ ok: true })
    })

    it.each<[string, () => unknown, Partial<SandboxRecipientCheckRequest>, string]>([
        ['a suppressed address', () => suppression.recordComplaints(teamId, [address], 'abuse'), {}, 'suppressed'],
        [
            'a hard-bounced address on a transactional step',
            () => suppression.recordHardBounces(teamId, [address], 'mailbox does not exist'),
            { categoryType: 'transactional' },
            'suppressed',
        ],
        [
            'a suppressed address on a test send',
            () => suppression.recordComplaints(teamId, [address], 'abuse'),
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

    it.each<[string, string, Partial<SandboxRecipientCheckRequest>]>([
        ['the opt-out lookup', 'fetchCDPRecipients', {}],
        ['the suppression lookup', 'loadSuppressed', {}],
        ['the suppression lookup on a transactional step', 'loadSuppressed', { categoryType: 'transactional' }],
    ])('blocks for a retry when %s fails', async (_case, failingQuery, request) => {
        failQuery(failingQuery)
        expect(await check(request)).toEqual({ ok: false, reason: 'authorization_unavailable' })
    })

    it.each<[string, () => unknown, Partial<SandboxRecipientCheckRequest>]>([
        [
            'a complaint on a transactional step',
            () => suppression.recordComplaints(teamId, [address], 'abuse'),
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
