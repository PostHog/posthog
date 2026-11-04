import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { getDefaultZScoreDetectorConfig } from '../logic/detectorConfigDefaults'
import { DetectorSelector } from './DetectorSelector'

describe('DetectorSelector', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        ['an intermediate zero while backspacing', '0', 0],
        ['a valid threshold', '0.8', 0.8],
        ['an empty field', '', 0.95],
    ])('commits %s to the anomaly threshold', (_, typed, expected) => {
        const onChange = jest.fn()
        render(<DetectorSelector value={getDefaultZScoreDetectorConfig(30)} onChange={onChange} />)

        const thresholdInput = screen.getByDisplayValue('0.95')
        fireEvent.change(thresholdInput, { target: { value: typed } })

        expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ threshold: expected }))
    })
})
