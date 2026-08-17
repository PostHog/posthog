import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FeatureFlagGroupType, PropertyFilterType, PropertyOperator } from '~/types'

import { defaultReleaseConditionsLogic } from './defaultReleaseConditionsLogic'

describe('defaultReleaseConditionsLogic', () => {
    let logic: ReturnType<typeof defaultReleaseConditionsLogic.build>

    const groupWithBigIntId = (value: bigint): FeatureFlagGroupType => ({
        properties: [{ key: 'id', value, type: PropertyFilterType.Person, operator: PropertyOperator.Exact }],
        rollout_percentage: 100,
        variant: null,
    })

    beforeEach(async () => {
        initKeaTests()
        logic = defaultReleaseConditionsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadDefaultReleaseConditionsSuccess'])
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('loadError', () => {
        // Drives the panel's failure banner: it must set on a failed load so the admin can tell
        // "couldn't load" from "no defaults configured", and clear on a successful retry.
        it('sets on a failed load and clears on a successful retry', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/default_release_conditions/': () => [500, {}],
                },
            })
            logic.actions.loadDefaultReleaseConditions()
            await expectLogic(logic)
                .toDispatchActions(['loadDefaultReleaseConditionsFailure'])
                .toMatchValues({ loadError: true })

            useMocks({
                get: {
                    '/api/environments/:team_id/default_release_conditions/': () => [
                        200,
                        { enabled: false, default_groups: [] },
                    ],
                },
            })
            logic.actions.loadDefaultReleaseConditions()
            await expectLogic(logic)
                .toDispatchActions(['loadDefaultReleaseConditionsSuccess'])
                .toMatchValues({ loadError: false })
        })
    })

    describe('hasChanges', () => {
        // hasChanges used to compare groups via raw JSON.stringify, which throws on bigint
        // property values (PropertyFilterBaseValue allows bigint).
        it.each([
            { candidateValue: BigInt('9007199254740993'), expected: false },
            { candidateValue: BigInt('9007199254740994'), expected: true },
        ])(
            'does not throw and reports hasChanges=$expected for a bigint property value',
            ({ candidateValue, expected }) => {
                logic.actions.loadDefaultReleaseConditionsSuccess({
                    enabled: true,
                    default_groups: [groupWithBigIntId(BigInt('9007199254740993'))],
                })

                expect(() => {
                    logic.actions.setLocalGroups([groupWithBigIntId(candidateValue)])
                }).not.toThrow()

                expectLogic(logic).toMatchValues({ hasChanges: expected })
            }
        )
    })
})
