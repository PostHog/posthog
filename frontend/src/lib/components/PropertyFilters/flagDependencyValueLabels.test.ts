import {
    getFlagDependencyValueLabel,
    getFlagDependencyValueTooltip,
    isFlagDependencyBooleanValue,
} from './flagDependencyValueLabels'

describe('flagDependencyValueLabels', () => {
    it('detects boolean-like dependency values', () => {
        expect(isFlagDependencyBooleanValue(true)).toBe(true)
        expect(isFlagDependencyBooleanValue(false)).toBe(true)
        expect(isFlagDependencyBooleanValue('true')).toBe(true)
        expect(isFlagDependencyBooleanValue('false')).toBe(true)
        expect(isFlagDependencyBooleanValue('control')).toBe(false)
    })

    it('returns labels for true/false', () => {
        expect(getFlagDependencyValueLabel(true)).toBe('Evaluate true')
        expect(getFlagDependencyValueLabel(false)).toBe('Evaluate false')
        expect(getFlagDependencyValueLabel('variant-a')).toBe('variant-a')
    })

    it('returns tooltips for boolean-like values only', () => {
        expect(getFlagDependencyValueTooltip(true)).toContain('evaluates to true')
        expect(getFlagDependencyValueTooltip(false)).toContain('evaluates to false')
        expect(getFlagDependencyValueTooltip('variant')).toBeUndefined()
    })
})
