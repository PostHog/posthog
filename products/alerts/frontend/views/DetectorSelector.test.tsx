import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { AlertCalculationInterval } from '~/queries/schema/schema-general'

import { getDefaultZScoreDetectorConfig } from '../logic/detectorConfigDefaults'
import { getDefaultForecastDetectorConfig } from '../logic/forecastRules'
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

    it.each([
        ['the flag is off', false, AlertCalculationInterval.DAILY, false],
        ['the flag is on', true, AlertCalculationInterval.DAILY, true],
        ['the alert runs in real time', true, AlertCalculationInterval.REAL_TIME, false],
    ])('offers the forecast detector only when %s', (_, forecastDetectorEnabled, interval, offered) => {
        render(
            <DetectorSelector
                value={getDefaultZScoreDetectorConfig(30)}
                onChange={jest.fn()}
                calculationInterval={interval}
                forecastDetectorEnabled={forecastDetectorEnabled}
            />
        )

        fireEvent.click(screen.getByText('Z-Score'))

        expect(!!screen.queryByText('Forecast')).toBe(offered)
    })

    it.each([
        [
            'turning off spikes keeps only the drop rule',
            () => fireEvent.click(screen.getByText('Fire on spikes')),
            { type: 'forecast', below: { quantile: 0.01 } },
        ],
        [
            'a minimum change in percent is stored as a fraction',
            () =>
                fireEvent.change(screen.getByLabelText('Minimum change above expected, in percent'), {
                    target: { value: '20' },
                }),
            { type: 'forecast', above: { quantile: 0.99, min_relative_change: 0.2 }, below: { quantile: 0.01 } },
        ],
    ])('forecast rule: %s', (_, act, expected) => {
        const onChange = jest.fn()
        render(<DetectorSelector value={getDefaultForecastDetectorConfig()} onChange={onChange} />)

        act()

        expect(onChange).toHaveBeenLastCalledWith(expected)
    })
})
