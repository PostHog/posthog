import { getAiSubscriptionGate, getNextDeliveryDate } from './utils'

describe('getNextDeliveryDate', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2024-01-15T12:00:00Z'))
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        ['frequency is missing', { start_date: '2024-01-01T09:00:00Z' }],
        ['start_date is missing', { frequency: 'daily' }],
        ['subscription is empty', {}],
    ] as const)('returns null when %s', (_label, subscription) => {
        expect(getNextDeliveryDate(subscription)).toBeNull()
    })

    it.each([
        ['with explicit interval', { frequency: 'daily', interval: 1, start_date: '2024-01-01T09:00:00Z' }],
        ['defaulting interval to 1', { frequency: 'daily', start_date: '2024-01-01T09:00:00Z' }],
    ] as const)('computes next daily delivery %s', (_label, subscription) => {
        expect(getNextDeliveryDate(subscription)).toEqual(new Date('2024-01-16T09:00:00Z'))
    })

    it('computes next weekly delivery', () => {
        const result = getNextDeliveryDate({
            frequency: 'weekly',
            interval: 1,
            start_date: '2024-01-01T09:00:00Z',
            byweekday: ['wednesday'],
        })
        expect(result).toEqual(new Date('2024-01-17T09:00:00Z'))
    })

    it('computes next monthly delivery with bysetpos', () => {
        const result = getNextDeliveryDate({
            frequency: 'monthly',
            interval: 1,
            start_date: '2024-01-01T09:00:00Z',
            byweekday: ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'],
            bysetpos: 1,
        })
        // First weekday of Feb 2024 is Thu Feb 1
        expect(result).toEqual(new Date('2024-02-01T09:00:00Z'))
    })

    it('returns null on invalid rrule config', () => {
        const result = getNextDeliveryDate({
            frequency: 'invalid_freq' as any,
            start_date: '2024-01-01T09:00:00Z',
        })
        expect(result).toBeNull()
    })
})

describe('getAiSubscriptionGate', () => {
    // Fully-enabled baseline (insight flow, new sub, consent + cloud + flag all on); each case overrides.
    const base = {
        isAiPrompt: false,
        isParentless: false,
        isEditing: false,
        aiConsentApproved: true,
        isCloud: true,
        isDebug: false,
        aiFlagEnabled: true,
    } as const

    it.each([
        [
            'flag off hides every AI affordance',
            { aiFlagEnabled: false },
            { aiAllowed: false, showResourceTypeToggle: false, showConsentHint: false, showAiFormConsentBanner: false },
        ],
        [
            'flag on + consent + cloud fully enables AI',
            {},
            {
                aiAllowed: true,
                showResourceTypeToggle: true,
                aiOptionEnabled: true,
                showConsentHint: false,
                submitBlocked: false,
            },
        ],
        [
            'flag on + no consent greys AI and shows the consent hint (insight flow)',
            { aiConsentApproved: false },
            { aiAllowed: false, showResourceTypeToggle: true, aiOptionEnabled: false, showConsentHint: true },
        ],
        [
            'top-level AI form blocks submit and shows the banner when consent is missing',
            { isParentless: true, isAiPrompt: true, aiConsentApproved: false },
            { showResourceTypeToggle: false, showAiFormConsentBanner: true, submitBlocked: true },
        ],
        [
            'editing an AI sub never blocks, even without consent',
            { isEditing: true, isAiPrompt: true, aiConsentApproved: false },
            { showAiFormConsentBanner: false, submitBlocked: false, showResourceTypeToggle: false },
        ],
        ['debug mode satisfies the cloud requirement locally', { isCloud: false, isDebug: true }, { aiAllowed: true }],
        [
            'flag off shows no misleading consent banner on the AI-only form (but still blocks submit)',
            { isParentless: true, isAiPrompt: true, aiFlagEnabled: false, aiConsentApproved: false },
            { showAiFormConsentBanner: false, submitBlocked: true },
        ],
    ] as const)('%s', (_label, overrides, expected) => {
        expect(getAiSubscriptionGate({ ...base, ...overrides })).toMatchObject(expected)
    })
})
