import { stateLabel, stateTagType } from './billingAlertDisplay'

describe('billingAlertDisplay', () => {
    it('gives broken state precedence over disabled status', () => {
        expect(stateTagType('broken', false)).toBe('danger')
        expect(stateLabel('broken', false)).toBe('broken')
    })

    it('shows other disabled alerts as paused', () => {
        expect(stateTagType('not_firing', false)).toBe('muted')
        expect(stateLabel('not_firing', false)).toBe('Paused')
    })
})
