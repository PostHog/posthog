import { expectLogic, partial } from 'kea-test-utils'

import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { Experiment } from '~/types'

import { NEW_EXPERIMENT } from '../constants'
import { experimentsLogic } from '../experimentsLogic'
import { createExperimentLogic } from './createExperimentLogic'
import { variantsPanelLogic } from './variantsPanelLogic'

describe('variantsPanelLogic', () => {
    let logic: ReturnType<typeof variantsPanelLogic.build>

    const mockExperiment: Experiment = {
        ...NEW_EXPERIMENT,
        id: 1,
        name: 'Test Experiment',
        feature_flag_key: 'test-experiment',
    }

    const mockFeatureFlags = [
        {
            id: 1,
            key: 'existing-flag-1',
            name: 'Existing Flag 1',
            filters: {
                groups: [],
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                },
            },
            active: true,
            deleted: false,
            ensure_experience_continuity: false,
        },
        {
            id: 2,
            key: 'existing-flag-2',
            name: 'Existing Flag 2',
            filters: {
                groups: [],
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 33 },
                        { key: 'variant-a', rollout_percentage: 33 },
                        { key: 'variant-b', rollout_percentage: 34 },
                    ],
                },
            },
            active: true,
            deleted: false,
            ensure_experience_continuity: false,
        },
        {
            id: 3,
            key: 'invalid-flag',
            name: 'Invalid Flag (no multivariate)',
            filters: {
                groups: [],
            },
            active: true,
            deleted: false,
            ensure_experience_continuity: false,
        },
    ]

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/@current/feature_flags/': (req) => {
                    const url = new URL(req.url)
                    const search = url.searchParams.get('search')

                    if (search) {
                        const filtered = mockFeatureFlags.filter((flag) =>
                            flag.key.toLowerCase().includes(search.toLowerCase())
                        )
                        return [200, { results: filtered, count: filtered.length }]
                    }

                    return [200, { results: mockFeatureFlags, count: mockFeatureFlags.length }]
                },
                '/api/projects/@current/experiments': () => [
                    200,
                    {
                        results: [
                            { id: 1, name: 'Experiment 1', feature_flag_key: 'experiment-flag-1' },
                            { id: 2, name: 'Experiment 2', feature_flag_key: 'experiment-flag-2' },
                        ],
                        count: 2,
                    },
                ],
            },
        })
        initKeaTests()

        // Mount and load connected logics to populate their data
        featureFlagsLogic.mount()
        featureFlagsLogic.actions.loadFeatureFlags()

        experimentsLogic.mount()
        experimentsLogic.actions.loadExperiments()

        logic = variantsPanelLogic({ experiment: mockExperiment })
        logic.mount()
        jest.clearAllMocks()
    })

    afterEach(() => {
        logic.unmount()
        featureFlagsLogic.unmount()
        experimentsLogic.unmount()
    })

    describe('mode management', () => {
        it('defaults to create mode', async () => {
            await expectLogic(logic).toMatchValues({
                mode: 'create',
            })
        })

        it('switches to link mode', async () => {
            await expectLogic(logic, () => {
                logic.actions.setMode('link')
            })
                .toDispatchActions(['setMode'])
                .toMatchValues({
                    mode: 'link',
                })
        })

        it('resets dirty flag when switching modes', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFeatureFlagKeyDirty()
                logic.actions.setMode('link')
            })
                .toDispatchActions(['setFeatureFlagKeyDirty', 'setMode'])
                .toMatchValues({
                    featureFlagKeyDirty: false,
                })
        })
    })

    describe('feature flag key validation', () => {
        it('validates valid feature flag key', async () => {
            await expectLogic(logic, () => {
                logic.actions.validateFeatureFlagKey('valid-flag-key')
            })
                .toDispatchActions(['validateFeatureFlagKey', 'validateFeatureFlagKeySuccess'])
                .toMatchValues({
                    featureFlagKeyValidation: partial({
                        valid: true,
                        error: null,
                    }),
                })
        })

        it('rejects empty feature flag key', async () => {
            await expectLogic(logic, () => {
                logic.actions.validateFeatureFlagKey('')
            })
                .toDispatchActions(['validateFeatureFlagKey', 'validateFeatureFlagKeySuccess'])
                .toMatchValues({
                    featureFlagKeyValidation: partial({
                        valid: false,
                        error: expect.any(String),
                    }),
                })
        })

        it('rejects feature flag key with invalid characters', async () => {
            await expectLogic(logic, () => {
                logic.actions.validateFeatureFlagKey('invalid key with spaces!')
            })
                .toDispatchActions(['validateFeatureFlagKey', 'validateFeatureFlagKeySuccess'])
                .toMatchValues({
                    featureFlagKeyValidation: partial({
                        valid: false,
                        error: expect.any(String),
                    }),
                })
        })

        it('rejects feature flag key that already exists in unavailable keys', async () => {
            await expectLogic(logic, () => {
                logic.actions.validateFeatureFlagKey('existing-flag-1')
            })
                .toDispatchActions(['validateFeatureFlagKey', 'validateFeatureFlagKeySuccess'])
                .toMatchValues({
                    featureFlagKeyValidation: partial({
                        valid: false,
                        error: 'A feature flag with this key already exists.',
                    }),
                })
        })

        it('debounces validation calls', async () => {
            const spy = jest.spyOn(logic.actions, 'validateFeatureFlagKey')

            await expectLogic(logic, () => {
                logic.actions.validateFeatureFlagKey('test-1')
                logic.actions.validateFeatureFlagKey('test-2')
                logic.actions.validateFeatureFlagKey('test-3')
            })
                .delay(350)
                .toDispatchActions([
                    'validateFeatureFlagKey',
                    'validateFeatureFlagKey',
                    'validateFeatureFlagKey',
                    'validateFeatureFlagKeySuccess',
                ])
                .toMatchValues({
                    featureFlagKeyValidation: partial({
                        valid: true,
                        error: null,
                    }),
                })

            expect(spy).toHaveBeenCalledTimes(3)
            expect(spy).toHaveBeenLastCalledWith('test-3')
        })
    })

    describe('feature flag key generation', () => {
        it('generates feature flag key from experiment name', async () => {
            await expectLogic(logic, () => {
                logic.actions.generateFeatureFlagKey('My Awesome Experiment')
            })
                .toDispatchActions(['generateFeatureFlagKey', 'generateFeatureFlagKeySuccess'])
                .toMatchValues({
                    generatedKey: 'my-awesome-experiment',
                })
        })

        it('handles special characters in experiment name', async () => {
            await expectLogic(logic, () => {
                logic.actions.generateFeatureFlagKey('Test@#$%Experiment!!!')
            })
                .toDispatchActions(['generateFeatureFlagKey', 'generateFeatureFlagKeySuccess'])
                .toMatchValues({
                    generatedKey: 'test-experiment',
                })
        })

        it.skip('adds counter suffix when key already exists', async () => {
            // Note: This test requires connected logics (featureFlagsLogic/experimentsLogic) to be fully loaded
            // which is complex to set up in unit tests. The integration is tested in component tests.
            await expectLogic(logic, () => {
                logic.actions.generateFeatureFlagKey('existing-flag-1')
            })
                .toDispatchActions(['generateFeatureFlagKey', 'generateFeatureFlagKeySuccess'])
                .toMatchValues({
                    generatedKey: 'existing-flag-1-1',
                })
        })

        it('returns null for empty name', async () => {
            await expectLogic(logic, () => {
                logic.actions.generateFeatureFlagKey('')
            })
                .toDispatchActions(['generateFeatureFlagKey', 'generateFeatureFlagKeySuccess'])
                .toMatchValues({
                    generatedKey: null,
                })
        })

        it('auto-generates key when experiment name changes in create mode', async () => {
            const createLogic = createExperimentLogic()
            createLogic.mount()

            await expectLogic(logic, () => {
                createLogic.actions.setExperimentValue('name', 'New Experiment Name')
            }).toDispatchActions([
                createExperimentLogic.actionTypes.setExperimentValue,
                'generateFeatureFlagKey',
                'generateFeatureFlagKeySuccess',
            ])

            createLogic.unmount()
        })

        it('does not auto-generate key when dirty flag is set', async () => {
            const createLogic = createExperimentLogic()
            createLogic.mount()

            logic.actions.setFeatureFlagKeyDirty()

            await expectLogic(logic, () => {
                createLogic.actions.setExperimentValue('name', 'New Experiment Name')
            }).toNotHaveDispatchedActions(['generateFeatureFlagKey'])

            createLogic.unmount()
        })
    })

    describe('available feature flags', () => {
        it('loads all eligible feature flags', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadAllEligibleFeatureFlags()
            })
                .toDispatchActions(['loadAllEligibleFeatureFlags', 'loadAllEligibleFeatureFlagsSuccess'])
                .toMatchValues({
                    availableFeatureFlags: expect.arrayContaining([
                        partial({ key: 'existing-flag-1' }),
                        partial({ key: 'existing-flag-2' }),
                    ]),
                })
        })

        it('filters out non-eligible feature flags', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadAllEligibleFeatureFlags()
            })
                .toDispatchActions(['loadAllEligibleFeatureFlags', 'loadAllEligibleFeatureFlagsSuccess'])
                .toMatchValues({
                    availableFeatureFlags: expect.not.arrayContaining([partial({ key: 'invalid-flag' })]),
                })
        })

        it('searches feature flags by key', async () => {
            await expectLogic(logic, () => {
                logic.actions.searchFeatureFlags('flag-1')
            })
                .toDispatchActions(['searchFeatureFlags', 'searchFeatureFlagsSuccess'])
                .toMatchValues({
                    availableFeatureFlags: [partial({ key: 'existing-flag-1' })],
                })
        })

        it('resets search and clears results', async () => {
            await expectLogic(logic, () => {
                logic.actions.searchFeatureFlags('flag-1')
            }).toDispatchActions(['searchFeatureFlags', 'searchFeatureFlagsSuccess'])

            await expectLogic(logic, () => {
                logic.actions.resetFeatureFlagsSearch()
            })
                .toDispatchActions(['resetFeatureFlagsSearch', 'resetFeatureFlagsSearchSuccess'])
                .toMatchValues({
                    availableFeatureFlags: [],
                })
        })
    })

    describe('unavailableFeatureFlagKeys selector', () => {
        it.skip('combines feature flag keys and experiment keys', async () => {
            // Note: This test requires connected logics (featureFlagsLogic/experimentsLogic) to be fully loaded
            // which is complex to set up in unit tests. The integration is tested in component tests.
            // Wait for connected logics to load
            await expectLogic(featureFlagsLogic).toDispatchActions(['loadFeatureFlagsSuccess'])
            await expectLogic(experimentsLogic).toDispatchActions(['loadExperimentsSuccess'])

            await expectLogic(logic).toMatchValues({
                unavailableFeatureFlagKeys: expect.any(Set),
            })

            const keys = logic.values.unavailableFeatureFlagKeys
            expect(keys.has('existing-flag-1')).toBe(true)
            expect(keys.has('existing-flag-2')).toBe(true)
            expect(keys.has('experiment-flag-1')).toBe(true)
            expect(keys.has('experiment-flag-2')).toBe(true)
        })
    })

    describe('error handling', () => {
        it('handles validation errors gracefully', async () => {
            useMocks({
                get: {
                    '/api/projects/@current/feature_flags/': () => [500, { error: 'Server error' }],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.validateFeatureFlagKey('test-key')
            }).toDispatchActions(['validateFeatureFlagKey', 'validateFeatureFlagKeyFailure'])
        })

        it('handles feature flag loading errors', async () => {
            useMocks({
                get: {
                    '/api/projects/@current/feature_flags/': () => [500, { error: 'Server error' }],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.loadAllEligibleFeatureFlags()
            }).toDispatchActions(['loadAllEligibleFeatureFlags', 'loadAllEligibleFeatureFlagsFailure'])
        })
    })
})
