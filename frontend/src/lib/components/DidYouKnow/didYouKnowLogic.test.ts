import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'
import { toast } from 'react-toastify'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import {
    didYouKnowLogic,
    markDidYouKnowTipAsMastered,
    parseDidYouKnowPayload,
    tryShowDidYouKnow,
} from './didYouKnowLogic'
import { DID_YOU_KNOW_TIPS, didYouKnowFlagKey } from './didYouKnowTips'

jest.mock('posthog-js')

const TIP_KEY = DID_YOU_KNOW_TIPS.SQL_EDITOR_SHORTCUT
const FLAG_KEY = didYouKnowFlagKey(TIP_KEY)
const NOW = new Date('2026-11-02T12:00:00Z')
const PAYLOAD = {
    title: 'Did you know?',
    description: 'Type sql anywhere in PostHog to open the SQL editor.',
}

describe('didYouKnowLogic', () => {
    let logic: ReturnType<typeof didYouKnowLogic.build>
    let toastInfoSpy: jest.SpyInstance

    beforeEach(() => {
        window.localStorage.clear()
        initKeaTests()
        jest.useFakeTimers()
        jest.setSystemTime(NOW)
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FLAG_KEY]: true })
        jest.mocked(posthog.getFeatureFlagResult).mockReturnValue({ payload: PAYLOAD } as any)
        toastInfoSpy = jest.spyOn(toast, 'info').mockReturnValue('did-you-know-toast')
        logic = didYouKnowLogic()
        logic.mount()
        jest.mocked(posthog.capture).mockClear()
    })

    afterEach(() => {
        logic.unmount()
        featureFlagLogic.unmount()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('shows an eligible tip and records its exposure', async () => {
        await expectLogic(logic, () => logic.actions.tryShowTip(TIP_KEY)).toDispatchActions([
            'recordShown',
            'reportTipShown',
        ])

        expect(logic.values.lastShownAt).toBe(NOW.valueOf())
        expect(toastInfoSpy).toHaveBeenCalledTimes(1)
        expect(posthog.capture).toHaveBeenCalledWith('did you know shown', { tip_key: TIP_KEY })
    })

    it.each([
        ['dismissed', (mountedLogic: typeof logic) => mountedLogic.actions.dismissTip(TIP_KEY)],
        ['mastered', (mountedLogic: typeof logic) => mountedLogic.actions.markTipAsMastered(TIP_KEY)],
        ['inside the cooldown', (mountedLogic: typeof logic) => mountedLogic.actions.recordShown(NOW.valueOf())],
    ])('does not show a tip that is %s', async (_, applyGuard) => {
        applyGuard(logic)
        toastInfoSpy.mockClear()
        logic.actions.tryShowTip(TIP_KEY)
        await Promise.resolve()

        expect(toastInfoSpy).not.toHaveBeenCalled()
    })

    it('requires both an enabled flag and a valid payload', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FLAG_KEY]: false })
        logic.actions.tryShowTip(TIP_KEY)
        await Promise.resolve()

        featureFlagLogic.actions.setFeatureFlags([], { [FLAG_KEY]: true })
        jest.mocked(posthog.getFeatureFlagResult).mockReturnValue({ payload: null } as any)
        logic.actions.tryShowTip(TIP_KEY)
        await Promise.resolve()

        expect(logic.values.lastShownAt).toBeNull()
        expect(toastInfoSpy).not.toHaveBeenCalled()
    })

    it('replays an attempt made before the logic mounted', async () => {
        logic.unmount()
        tryShowDidYouKnow(TIP_KEY)
        expect(toastInfoSpy).not.toHaveBeenCalled()

        logic = didYouKnowLogic()
        await expectLogic(logic, () => {
            logic.mount()
        }).toDispatchActions(['tryShowTip', 'recordShown', 'reportTipShown'])

        expect(toastInfoSpy).toHaveBeenCalledTimes(1)
    })

    it('records mastery only once through the public helper', () => {
        markDidYouKnowTipAsMastered(TIP_KEY)
        markDidYouKnowTipAsMastered(TIP_KEY)

        expect(logic.values.masteredTips).toEqual({ [TIP_KEY]: true })
        expect(jest.mocked(posthog.capture).mock.calls).toEqual([['did you know mastered', { tip_key: TIP_KEY }]])
    })

    it('normalizes copy and drops unsafe action URLs', () => {
        expect(
            parseDidYouKnowPayload({
                title: ' ',
                description: '  Learn a shortcut.  ',
                action: { label: 'Open it', url: 'javascript:alert(1)' },
            })
        ).toEqual({ title: 'Did you know?', description: 'Learn a shortcut.', action: undefined })
        expect(parseDidYouKnowPayload({ description: '' })).toBeNull()
    })
})
