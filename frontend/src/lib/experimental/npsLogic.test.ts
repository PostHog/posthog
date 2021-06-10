import { npsLogic } from 'lib/experimental/npsLogic'
import { initKea } from '~/initKea'

jest.mock('posthog-js')

describe('NPS Logic', () => {
    let unmount: () => void
    beforeEach(() => {
        initKea()
        unmount = npsLogic.mount()
    })
    afterEach(() => {
        unmount?.()
    })

    test('defaults', () => {
        expect(Object.keys(npsLogic.values)).toEqual([
            'step',
            'hidden',
            'payload',
            'featureFlagEnabled',
            'userIsOldEnough',
            'npsPromptEnabled',
        ])

        expect(npsLogic.values.featureFlagEnabled).toEqual(false)
        expect(npsLogic.values.userIsOldEnough).toEqual(false)
        expect(npsLogic.values.npsPromptEnabled).toEqual(false)
    })

    test('can update step', () => {
        expect(npsLogic.values.step).toEqual(0)
        npsLogic.actions.setStep(1)
        expect(npsLogic.values.step).toEqual(1)
        npsLogic.actions.setStep(2)
        expect(npsLogic.values.step).toEqual(2)
    })
})
