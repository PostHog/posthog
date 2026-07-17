import type { Experiment } from '~/types'

import { NEW_EXPERIMENT } from '../constants'
import { validateExperimentSubmission } from './experimentSubmissionValidation'

describe('validateExperimentSubmission', () => {
    const WEB_CONTROL_ERROR = "Web experiments require a variant with key 'control'"

    const experimentWith = (type: Experiment['type'], variantKeys: string[]): Experiment => ({
        ...NEW_EXPERIMENT,
        name: 'My experiment',
        feature_flag_key: 'my-experiment',
        type,
        feature_flag_config: {
            filters: {
                multivariate: {
                    variants: variantKeys.map((key) => ({ key, rollout_percentage: 100 / variantKeys.length })),
                },
            },
        },
    })

    it.each([
        ['web', ['baseline', 'test'], true],
        ['web', ['control', 'test'], false],
        ['product', ['baseline', 'test'], false],
    ] as [Experiment['type'], string[], boolean][])(
        'a %s experiment with variants %p requires control: %s',
        (type, variantKeys, expectError) => {
            const { errors } = validateExperimentSubmission({
                experiment: experimentWith(type, variantKeys),
                featureFlagKeyValidation: null,
                mode: 'create',
                experimentErrors: {},
            })

            expect(errors.includes(WEB_CONTROL_ERROR)).toBe(expectError)
        }
    )
})
