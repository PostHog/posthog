import { PostgresRouter } from '~/common/utils/db/postgres'

import { MessageOptOutRecord } from '../../../types'
import { PreferenceStatus, RecipientsManagerService } from '../../managers/recipients-manager.service'
import { SuppressionLookupError } from '../email-suppression.service'
import { FrequencyCapCheck } from '../recipient-preferences.service'
import { SandboxRecipientCheckRequest, checkSandboxRecipient } from './sandbox-recipient-checks'

const address = 'member@example.com'

describe('checkSandboxRecipient', () => {
    let suppressed: 'none' | 'complaint' | 'hard_bounce' | 'unreadable'
    let preferences: Record<string, PreferenceStatus>
    let frequencyCap: jest.Mock<Promise<FrequencyCapCheck>, []>
    let recipients: RecipientsManagerService

    const check = (request: Partial<SandboxRecipientCheckRequest> = {}) =>
        checkSandboxRecipient(
            {
                suppression: {
                    isSuppressed: (_teamId, _email, { transactional = false } = {}) =>
                        suppressed === 'unreadable'
                            ? Promise.reject(new SuppressionLookupError())
                            : Promise.resolve(
                                  suppressed === 'hard_bounce' || (suppressed === 'complaint' && !transactional)
                              ),
                },
                recipients,
            },
            {
                teamId: 1,
                address,
                categoryId: 'newsletter',
                categoryType: 'marketing',
                optOuts: [],
                isTest: false,
                frequencyCap,
                ...request,
            }
        )

    beforeEach(() => {
        suppressed = 'none'
        preferences = {}
        frequencyCap = jest.fn().mockResolvedValue({ capped: false })
        recipients = new RecipientsManagerService({} as PostgresRouter)
        jest.spyOn(recipients, 'get').mockImplementation(() =>
            Promise.resolve({
                id: 'recipient',
                team_id: 1,
                identifier: address,
                preferences,
                created_at: '',
                updated_at: '',
            })
        )
    })

    it('admits a recipient with no suppression, opt-out, or cap', async () => {
        expect(await check()).toEqual({ ok: true })
        expect(frequencyCap).toHaveBeenCalledTimes(1)
    })

    it.each<[string, () => void, Partial<SandboxRecipientCheckRequest>, string]>([
        ['a suppressed address', () => (suppressed = 'complaint'), {}, 'suppressed'],
        [
            'a hard-bounced address on a transactional step',
            () => (suppressed = 'hard_bounce'),
            { categoryType: 'transactional' },
            'suppressed',
        ],
        ['a suppressed address on a test send', () => (suppressed = 'complaint'), { isTest: true }, 'suppressed'],
        ['an opt-out from the category', () => (preferences = { newsletter: 'OPTED_OUT' }), {}, 'opted_out'],
        ['an opt-out from all marketing', () => (preferences = { $all: 'OPTED_OUT' }), {}, 'opted_out'],
        [
            'an opt-out recorded earlier in the run',
            () => undefined,
            { optOuts: [{ identifier: address, categoryId: '$all' } as MessageOptOutRecord] },
            'opted_out',
        ],
        [
            'a person at the marketing frequency cap',
            () => frequencyCap.mockResolvedValue({ capped: true, nextSlotAt: 0, holdHours: 4 }),
            {},
            'frequency_capped',
        ],
    ])('refuses %s', async (_case, arrange, request, reason) => {
        arrange()
        expect(await check(request)).toEqual({ ok: false, reason })
    })

    it.each<[string, () => void, Partial<SandboxRecipientCheckRequest>]>([
        ['the opt-out lookup', () => jest.spyOn(recipients, 'get').mockRejectedValue(new Error('connection lost')), {}],
        ['the suppression lookup', () => (suppressed = 'unreadable'), {}],
        [
            'the suppression lookup on a transactional step',
            () => (suppressed = 'unreadable'),
            { categoryType: 'transactional' },
        ],
    ])('blocks for a retry when %s fails', async (_case, arrange, request) => {
        arrange()
        expect(await check(request)).toEqual({ ok: false, reason: 'authorization_unavailable' })
    })

    it.each<[string, () => void, Partial<SandboxRecipientCheckRequest>]>([
        ['a complaint on a transactional step', () => (suppressed = 'complaint'), { categoryType: 'transactional' }],
        [
            'an opt-out on a transactional step',
            () => (preferences = { $all: 'OPTED_OUT' }),
            { categoryType: 'transactional' },
        ],
        [
            'the frequency cap on a test send',
            () => frequencyCap.mockResolvedValue({ capped: true, nextSlotAt: 0, holdHours: null }),
            { isTest: true },
        ],
        [
            'the frequency cap on a transactional step',
            () => frequencyCap.mockResolvedValue({ capped: true, nextSlotAt: 0, holdHours: null }),
            { categoryType: 'transactional' },
        ],
    ])('lets through %s', async (_case, arrange, request) => {
        arrange()
        expect(await check(request)).toEqual({ ok: true })
    })
})
