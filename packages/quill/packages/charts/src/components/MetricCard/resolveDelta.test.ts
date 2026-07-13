import { type MetricChange, resolveDelta } from './resolveDelta'

const formatChange = (p: number): string => (p > 0 ? `+${p.toFixed(1)}%` : `${p.toFixed(1)}%`)

interface NullCase {
    name: string
    showChange: boolean
    change?: MetricChange | null
    fallbackChangePercent?: number | null
}

describe('resolveDelta', () => {
    it.each<NullCase>([
        { name: 'showChange is false, with a supplied change', showChange: false, change: { value: 5 } },
        { name: 'showChange is false, with a fallback percent', showChange: false, fallbackChangePercent: 5 },
        { name: 'change is null (suppression)', showChange: true, change: null },
        { name: 'no change and no fallback', showChange: true, fallbackChangePercent: null },
        { name: 'no change and fallback is NaN', showChange: true, fallbackChangePercent: NaN },
        { name: 'no change and fallback is Infinity', showChange: true, fallbackChangePercent: Infinity },
        { name: 'change.value is NaN', showChange: true, change: { value: NaN } },
        { name: 'change.value is Infinity', showChange: true, change: { value: Infinity } },
        {
            name: 'change.value is -Infinity, even with a label',
            showChange: true,
            change: { value: -Infinity, label: 'overridden' },
        },
    ])('returns null when $name', ({ showChange, change, fallbackChangePercent }) => {
        expect(
            resolveDelta({
                showChange,
                change,
                fallbackChangePercent: fallbackChangePercent ?? null,
                formatChange,
            })
        ).toBeNull()
    })

    it('uses the supplied change label verbatim when provided', () => {
        const result = resolveDelta({
            showChange: true,
            change: { value: 12.5, label: '+12.5% vs. last week' },
            fallbackChangePercent: 42,
            formatChange,
        })
        expect(result).toEqual({ value: 12.5, label: '+12.5% vs. last week' })
    })

    it('formats the supplied change value when no label is provided', () => {
        const result = resolveDelta({
            showChange: true,
            change: { value: -8 },
            fallbackChangePercent: null,
            formatChange,
        })
        expect(result).toEqual({ value: -8, label: '-8.0%' })
    })

    it('prefers the supplied change over the fallback percent', () => {
        const result = resolveDelta({
            showChange: true,
            change: { value: 1 },
            fallbackChangePercent: 99,
            formatChange,
        })
        expect(result?.value).toBe(1)
        expect(result?.label).toBe('+1.0%')
    })

    it('falls back to the computed percent when change is undefined', () => {
        const result = resolveDelta({
            showChange: true,
            change: undefined,
            fallbackChangePercent: 42.5,
            formatChange,
        })
        expect(result).toEqual({ value: 42.5, label: '+42.5%' })
    })
})
