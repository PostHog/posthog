import { expectLogic } from 'kea-test-utils'
import api from 'lib/api'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

import { initKeaTests } from '~/test/init'
import { FeatureFlagReleaseType } from '~/types'

import { relatedFeatureFlagsLogic } from './relatedFeatureFlagsLogic'

jest.mock('lib/api')

describe('relatedFeatureFlagsLogic', () => {
    let logic: ReturnType<typeof relatedFeatureFlagsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api, 'get').mockImplementation(async (url) => {
            if (url.includes('evaluation_reasons')) {
                return {
                    'flag-1': { value: true, evaluation: { reason: 'condition_match', condition_index: 0 } },
                    'flag-2': { value: false, evaluation: { reason: 'no_condition_match' } },
                    'flag-3': { value: true, evaluation: { reason: 'condition_match', condition_index: 1 } },
                }
            }
            return { results: [], count: 0 }
        })
    })

    afterEach(() => {
        logic?.unmount()
        jest.clearAllMocks()
    })

    describe('server-side filtering', () => {
        beforeEach(() => {
            const flagsLogic = featureFlagsLogic()
            flagsLogic.mount()

            logic = relatedFeatureFlagsLogic({ distinctId: 'test-user' })
            logic.mount()
        })

        it('should pass variants type filter correctly', async () => {
            const setFeatureFlagsFiltersSpy = jest.spyOn(featureFlagsLogic.actions, 'setFeatureFlagsFilters')

            await expectLogic(logic, () => {
                logic.actions.setFilters({ type: FeatureFlagReleaseType.Variants })
            })

            expect(setFeatureFlagsFiltersSpy).toHaveBeenCalledWith({ type: 'multivariant' }, false)
        })

        it('should pass active filter to featureFlagsLogic', async () => {
            const setFeatureFlagsFiltersSpy = jest.spyOn(featureFlagsLogic.actions, 'setFeatureFlagsFilters')

            await expectLogic(logic, () => {
                logic.actions.setFilters({ active: 'true' })
            })

            expect(setFeatureFlagsFiltersSpy).toHaveBeenCalledWith({ active: 'true' }, false)
        })

        it('should clear filters when user selects "all"', async () => {
            const setFeatureFlagsFiltersSpy = jest.spyOn(featureFlagsLogic.actions, 'setFeatureFlagsFilters')

            await expectLogic(logic, () => {
                logic.actions.setFilters({ type: FeatureFlagReleaseType.ReleaseToggle, active: 'true' })
            })

            await expectLogic(logic, () => {
                logic.actions.setFilters({ active: 'true' }, true)
            })

            expect(setFeatureFlagsFiltersSpy).toHaveBeenLastCalledWith({ active: 'true', type: undefined }, true)
        })

        it('should pass release toggle type filter correctly', async () => {
            const setFeatureFlagsFiltersSpy = jest.spyOn(featureFlagsLogic.actions, 'setFeatureFlagsFilters')

            await expectLogic(logic, () => {
                logic.actions.setFilters({ type: FeatureFlagReleaseType.ReleaseToggle })
            })

            expect(setFeatureFlagsFiltersSpy).toHaveBeenCalledWith({ type: 'boolean' }, false)
        })
    })
})
