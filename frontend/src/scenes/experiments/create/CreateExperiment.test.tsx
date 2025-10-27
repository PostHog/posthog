import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { Experiment } from '~/types'

import { NEW_EXPERIMENT } from '../constants'
import { createExperimentLogic } from './createExperimentLogic'

describe('CreateExperiment Integration', () => {
    let logic: ReturnType<typeof createExperimentLogic.build>
    let routerPushSpy: jest.SpyInstance

    beforeEach(() => {
        // Clear localStorage to prevent persisted state from affecting tests
        localStorage.clear()

        useMocks({
            post: {
                '/api/projects/@current/experiments': async (req) => {
                    const body = (await req.json()) as Experiment
                    return [
                        200,
                        {
                            id: 123,
                            name: body.name,
                            description: body.description,
                            type: body.type || 'product',
                            feature_flag: { id: 456 },
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

    describe('form state and validation', () => {
        it('initializes with default NEW_EXPERIMENT values', async () => {
            await expectLogic(logic).toMatchValues({
                experiment: expect.objectContaining({
                    id: 'new',
                    name: '',
                    description: '',
                    type: 'product',
                }),
            })
        })

        it('updates experiment state through setExperiment', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: 'My Test Experiment',
                    description: 'My hypothesis',
                })
            }).toMatchValues({
                experiment: expect.objectContaining({
                    name: 'My Test Experiment',
                    description: 'My hypothesis',
                }),
            })
        })

        it('validates and prevents submission with empty fields', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({ ...NEW_EXPERIMENT, name: '' })
                logic.actions.submitExperiment()
            })
                .toDispatchActions(['submitExperiment', 'submitExperimentFailure'])
                .toMatchValues({
                    experimentErrors: expect.objectContaining({
                        name: 'Name is required',
                    }),
                })
        })
    })

    describe('experiment type changes', () => {
        it('allows changing experiment type from product to web', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({ ...NEW_EXPERIMENT, type: 'web' })
            }).toMatchValues({
                experiment: expect.objectContaining({
                    type: 'web',
                }),
            })
        })

        it('defaults to product experiment type', async () => {
            await expectLogic(logic).toMatchValues({
                experiment: expect.objectContaining({
                    type: 'product',
                }),
            })
        })
    })

    describe('full submission flow', () => {
        it('successfully submits valid experiment and navigates', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: 'Test Experiment',
                    description: 'Test hypothesis',
                })
                logic.actions.submitExperiment()
            })
                .toDispatchActions(['submitExperiment', 'createExperimentSuccess'])
                .toFinishAllListeners()

            expect(routerPushSpy).toHaveBeenCalledWith('/experiments/123')
        })

        it('clears errors after successful submission', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({ ...NEW_EXPERIMENT, name: '', description: '' })
                logic.actions.submitExperiment()
            }).toMatchValues({
                experimentErrors: expect.objectContaining({
                    name: 'Name is required',
                }),
            })

            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: 'Valid Name',
                    description: 'Valid Description',
                })
                logic.actions.submitExperiment()
            })
                .toDispatchActions(['submitExperiment', 'createExperimentSuccess'])
                .toMatchValues({
                    experimentErrors: {},
                })
        })
    })
})
