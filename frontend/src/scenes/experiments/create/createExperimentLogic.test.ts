import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { Experiment } from '~/types'

import { NEW_EXPERIMENT } from '../constants'
import { createExperimentLogic } from './createExperimentLogic'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: {
        success: jest.fn(),
    },
}))

jest.mock('~/layout/panel-layout/ProjectTree/projectTreeLogic', () => ({
    refreshTreeItem: jest.fn(),
}))

describe('createExperimentLogic', () => {
    let logic: ReturnType<typeof createExperimentLogic.build>
    let routerPushSpy: jest.SpyInstance

    beforeEach(() => {
        // Clear localStorage to prevent persisted state from affecting tests
        localStorage.clear()

        useMocks({
            post: {
                '/api/projects/@current/experiments': async (req) => {
                    const body = (await req.json()) as Experiment
                    if (!body.name || !body.description) {
                        return [400, { detail: 'Validation error' }]
                    }
                    return [
                        200,
                        {
                            id: 123,
                            name: body.name,
                            description: body.description,
                            type: body.type || 'product',
                            feature_flag: {
                                id: 456,
                            },
                        },
                    ]
                },
            },
            patch: {
                '/api/environments/@current/add_product_intent/': () => [200, {}],
            },
        })
        initKeaTests()
        logic = createExperimentLogic()
        logic.mount()
        routerPushSpy = jest.spyOn(router.actions, 'push')
        jest.clearAllMocks()
    })

    afterEach(() => {
        logic.unmount()
        routerPushSpy.mockRestore()
    })

    describe('form validation', () => {
        it('prevents submission when name is empty and shows error', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: '',
                    description: 'Valid hypothesis',
                })
                logic.actions.submitExperiment()
            })
                .toDispatchActions(['setExperiment', 'submitExperiment', 'submitExperimentFailure'])
                .toMatchValues({
                    experimentErrors: partial({
                        name: 'Name is required',
                    }),
                })
        })

        it('prevents submission when description is empty and shows error', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: 'Valid name',
                    description: '',
                })
                logic.actions.submitExperiment()
            })
                .toDispatchActions(['setExperiment', 'submitExperiment', 'submitExperimentFailure'])
                .toMatchValues({
                    experimentErrors: partial({
                        description: 'Hypothesis is required',
                    }),
                })
        })

        it('shows both errors when both name and description are empty', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: '',
                    description: '',
                })
                logic.actions.submitExperiment()
            })
                .toDispatchActions(['setExperiment', 'submitExperiment', 'submitExperimentFailure'])
                .toMatchValues({
                    experimentErrors: partial({
                        name: 'Name is required',
                        description: 'Hypothesis is required',
                    }),
                })
        })

        it('allows submission with valid data', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: 'Test Experiment',
                    description: 'Test hypothesis',
                })
                logic.actions.submitExperiment()
            }).toDispatchActions(['setExperiment', 'submitExperiment', 'submitExperimentSuccess'])
        })
    })

    describe('createExperiment', () => {
        it('successfully creates experiment and triggers success action', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: 'Test Experiment',
                    description: 'Test hypothesis',
                    type: 'product',
                })
                logic.actions.submitExperiment()
            })
                .toDispatchActions(['setExperiment', 'submitExperiment', 'createExperimentSuccess'])
                .toMatchValues({
                    experimentErrors: {},
                })
        })

        it('refreshes tree items for experiment and feature flag after creation', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: 'Test Experiment',
                    description: 'Test hypothesis',
                })
                logic.actions.submitExperiment()
            }).toDispatchActions(['submitExperiment', 'createExperimentSuccess'])

            await new Promise((resolve) => setTimeout(resolve, 10))

            expect(refreshTreeItem).toHaveBeenCalledWith('experiment', '123')
            expect(refreshTreeItem).toHaveBeenCalledWith('feature_flag', '456')
        })

        it('navigates to experiment page after creation', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: 'Test Experiment',
                    description: 'Test hypothesis',
                })
                logic.actions.submitExperiment()
            }).toDispatchActions(['submitExperiment', 'createExperimentSuccess'])

            await new Promise((resolve) => setTimeout(resolve, 10))

            expect(routerPushSpy).toHaveBeenCalledWith('/experiments/123')
        })

        it('shows success toast with view button', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: 'Test Experiment',
                    description: 'Test hypothesis',
                })
                logic.actions.submitExperiment()
            }).toDispatchActions(['submitExperiment', 'createExperimentSuccess'])

            await new Promise((resolve) => setTimeout(resolve, 10))

            expect(lemonToast.success).toHaveBeenCalledWith(
                'Experiment created successfully!',
                expect.objectContaining({
                    button: expect.objectContaining({
                        label: 'View it',
                    }),
                })
            )

            const toastCall = (lemonToast.success as jest.Mock).mock.calls[0]
            const toastButton = toastCall[1].button
            toastButton.action()

            expect(routerPushSpy).toHaveBeenCalledTimes(2)
        })
    })

    describe('state management', () => {
        it('setExperiment updates the full experiment object', async () => {
            const newExperiment = {
                ...NEW_EXPERIMENT,
                name: 'Updated Name',
                description: 'Updated Description',
                type: 'web' as const,
            }

            await expectLogic(logic, () => {
                logic.actions.setExperiment(newExperiment)
            })
                .toDispatchActions(['setExperiment'])
                .toMatchValues({
                    experiment: partial({
                        name: 'Updated Name',
                        description: 'Updated Description',
                        type: 'web',
                    }),
                })
        })

        it('form defaults to NEW_EXPERIMENT', async () => {
            await expectLogic(logic).toMatchValues({
                experiment: partial({
                    id: 'new',
                    name: '',
                    description: '',
                    type: 'product',
                }),
            })
        })

        it('setExperimentValue updates a single field', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperimentValue('name', 'New Name')
            })
                .toDispatchActions(['setExperimentValue'])
                .toMatchValues({
                    experiment: partial({
                        name: 'New Name',
                    }),
                })
        })

        it('setExperimentValue updates feature_flag_key', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperimentValue('feature_flag_key', 'new-flag-key')
            })
                .toDispatchActions(['setExperimentValue'])
                .toMatchValues({
                    experiment: partial({
                        feature_flag_key: 'new-flag-key',
                    }),
                })
        })

        it('setExperimentValue updates parameters object', async () => {
            const parameters = {
                feature_flag_variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ],
                ensure_experience_continuity: true,
            }

            await expectLogic(logic, () => {
                logic.actions.setExperimentValue('parameters', parameters)
            })
                .toDispatchActions(['setExperimentValue'])
                .toMatchValues({
                    experiment: partial({
                        parameters: partial({
                            feature_flag_variants: expect.arrayContaining([
                                partial({ key: 'control', rollout_percentage: 50 }),
                                partial({ key: 'test', rollout_percentage: 50 }),
                            ]),
                            ensure_experience_continuity: true,
                        }),
                    }),
                })
        })

        it('merges parameters when updating variants', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperimentValue('parameters', {
                    feature_flag_variants: [
                        { key: 'control', rollout_percentage: 33 },
                        { key: 'test', rollout_percentage: 33 },
                        { key: 'test-2', rollout_percentage: 34 },
                    ],
                })
            })
                .toDispatchActions(['setExperimentValue'])
                .toMatchValues({
                    experiment: partial({
                        parameters: partial({
                            feature_flag_variants: expect.arrayContaining([
                                partial({ key: 'control' }),
                                partial({ key: 'test' }),
                                partial({ key: 'test-2' }),
                            ]),
                        }),
                    }),
                })

            // Verify we have exactly 3 variants
            expect(logic.values.experiment.parameters?.feature_flag_variants).toHaveLength(3)
        })
    })

    describe('feature flag integration', () => {
        it('includes feature flag key in experiment submission', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: 'Test Experiment',
                    description: 'Test hypothesis',
                    feature_flag_key: 'custom-flag-key',
                })
                logic.actions.submitExperiment()
            }).toDispatchActions(['setExperiment', 'submitExperiment', 'createExperimentSuccess'])
        })

        it('includes variants in experiment submission', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: 'Test Experiment',
                    description: 'Test hypothesis',
                    feature_flag_key: 'test-flag',
                    parameters: {
                        feature_flag_variants: [
                            { key: 'control', rollout_percentage: 50 },
                            { key: 'treatment', rollout_percentage: 50 },
                        ],
                    },
                })
                logic.actions.submitExperiment()
            }).toDispatchActions(['setExperiment', 'submitExperiment', 'createExperimentSuccess'])
        })

        it('includes experience continuity setting in submission', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: 'Test Experiment',
                    description: 'Test hypothesis',
                    parameters: {
                        feature_flag_variants: [
                            { key: 'control', rollout_percentage: 50 },
                            { key: 'test', rollout_percentage: 50 },
                        ],
                    },
                })
                logic.actions.submitExperiment()
            }).toDispatchActions(['setExperiment', 'submitExperiment', 'createExperimentSuccess'])
        })
    })
})
