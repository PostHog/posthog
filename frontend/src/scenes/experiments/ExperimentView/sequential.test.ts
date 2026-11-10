import { ExperimentStatsMethod } from '~/types'

import { experimentUsesSequentialTesting } from './sequential'

describe('experimentUsesSequentialTesting', () => {
    it.each([
        ['an unset choice inherits an enabled team default', ExperimentStatsMethod.Frequentist, {}, true, true],
        [
            'an explicit choice overrides the team default',
            ExperimentStatsMethod.Frequentist,
            { sequential_testing_enabled: false },
            true,
            false,
        ],
        [
            'a Bayesian experiment never uses it',
            ExperimentStatsMethod.Bayesian,
            { sequential_testing_enabled: true },
            true,
            false,
        ],
    ])('%s', (_, method, frequentist, teamDefaultEnabled, expected) => {
        expect(experimentUsesSequentialTesting({ method, frequentist }, teamDefaultEnabled)).toBe(expected)
    })
})
