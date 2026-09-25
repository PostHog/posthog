import { fireEvent, render } from '@testing-library/react'

import { SingleDetectorConfig } from '~/queries/schema/schema-general'

import { DetectorSelector } from './DetectorSelector'

describe('DetectorSelector', () => {
    // A stored config is wider than the schema type: the API emits null for a floor that was
    // never set, so every alert saved without one comes back with min_baseline null.
    type StoredConfig = Record<string, unknown>

    function renderSelector(config: StoredConfig): {
        minBaseline: HTMLInputElement
        onChange: jest.Mock
        rerenderWith: (next: StoredConfig) => void
    } {
        const onChange = jest.fn()
        const element = (next: StoredConfig): JSX.Element => (
            <DetectorSelector value={next as unknown as SingleDetectorConfig} onChange={onChange} />
        )
        const { container, rerender } = render(element(config))
        return {
            minBaseline: container.querySelector<HTMLInputElement>(
                '[data-attr="alertForm-detector-min-baseline"]'
            ) as HTMLInputElement,
            onChange,
            rerenderWith: (next) => rerender(element(next)),
        }
    }

    it('does not hold a typed value the stored config never took', () => {
        const { minBaseline, rerenderWith } = renderSelector({ type: 'zscore', min_baseline: null })
        expect(minBaseline.value).toBe('')
        expect(minBaseline.placeholder).toBe('5')

        fireEvent.change(minBaseline, { target: { value: '7' } })
        rerenderWith({ type: 'zscore', min_baseline: null })

        expect(minBaseline.value).toBe('')
    })

    it('keeps an explicit zero floor', () => {
        const { minBaseline } = renderSelector({ type: 'zscore', min_baseline: 0 })

        expect(minBaseline.value).toBe('0')
    })

    it('reports a cleared field as unset, not as a floor of zero', () => {
        const { minBaseline, onChange } = renderSelector({ type: 'zscore', min_baseline: 12 })
        expect(minBaseline.value).toBe('12')

        fireEvent.change(minBaseline, { target: { value: '' } })

        expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ min_baseline: undefined }))
    })

    // Switching the detector type rebuilds the config from defaults, which carry no floor. The
    // field has to follow the config instead of holding the number the user typed.
    it('clears the field when the config drops the floor', () => {
        const { minBaseline, rerenderWith } = renderSelector({ type: 'zscore', min_baseline: 7 })
        expect(minBaseline.value).toBe('7')

        rerenderWith({ type: 'zscore' })

        expect(minBaseline.value).toBe('')
    })
})
