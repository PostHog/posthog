import { AlertConfig, supportsAnomalyDetection } from './types'

describe('supportsAnomalyDetection', () => {
    it.each([
        ['trends', { type: 'TrendsAlertConfig', series_index: 0 } as AlertConfig, true],
        ['SQL last_row', { type: 'HogQLAlertConfig', evaluation: 'last_row' } as AlertConfig, true],
        ['SQL first_row', { type: 'HogQLAlertConfig', evaluation: 'first_row' } as AlertConfig, true],
        ['SQL any_row', { type: 'HogQLAlertConfig', evaluation: 'any_row' } as AlertConfig, false],
        ['null', null, false],
    ])('%s -> %s', (_name, config, expected) => {
        expect(supportsAnomalyDetection(config)).toBe(expected)
    })
})
