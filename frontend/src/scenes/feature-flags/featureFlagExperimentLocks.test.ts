import { FeatureFlagType } from '~/types'

import { getExperimentLockReasons, getRunningLinkedExperiment } from './featureFlagExperimentLocks'

describe('featureFlagExperimentLocks', () => {
    it('finds the running experiment linked to a flag', () => {
        const flag: Pick<FeatureFlagType, 'experiment_set_metadata'> = {
            experiment_set_metadata: [
                { id: 1, name: 'Stopped test', is_running: false },
                { id: 2, name: 'Checkout copy', is_running: true },
            ],
        }

        expect(getRunningLinkedExperiment(flag)).toEqual({ id: 2, name: 'Checkout copy' })
    })

    it.each([
        ['no linked experiment', null],
        ['an empty experiment list', []],
        ['a draft or stopped experiment', [{ id: 1, name: 'Checkout copy', is_running: false }]],
    ])('leaves variants editable with %s', (_, experiment_set_metadata) => {
        const flag: Pick<FeatureFlagType, 'experiment_set_metadata'> = { experiment_set_metadata }

        const experiment = getRunningLinkedExperiment(flag)
        expect(experiment).toBeNull()
        expect(getExperimentLockReasons(experiment)).toEqual({})
    })

    it('names the experiment in every lock reason', () => {
        const reasons = getExperimentLockReasons({ id: 2, name: 'Checkout copy' })

        expect(reasons.variantKey).toContain('Checkout copy')
        expect(reasons.removeVariant).toContain('Checkout copy')
        expect(reasons.flagType).toContain('Checkout copy')
    })
})
