import { shouldSubmitDelegate } from './OnboardingExitModal'

describe('shouldSubmitDelegate', () => {
    it('blocks submit while IME composition is active', () => {
        expect(shouldSubmitDelegate(true)).toEqual(false)
    })

    it('allows submit when IME composition is inactive', () => {
        expect(shouldSubmitDelegate(false)).toEqual(true)
    })
})
