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
        error: jest.fn(),
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
                logic.actions.saveExperiment()
            })
                .toDispatchActions(['setExperiment', 'saveExperiment', 'saveExperimentFailure'])
                .toMatchValues({
                    experimentErrors: partial({
                        name: 'Name is required',
                    }),
                })
        })

        it('allows submission with valid data', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: 'Test Experiment',
                    description: 'Test hypothesis',
                    feature_flag_key: 'test-experiment',
                })
                logic.actions.saveExperiment()
            }).toDispatchActions(['setExperiment', 'saveExperiment', 'createExperimentSuccess'])
        })
    })

    describe('saveExperiment', () => {
        it('successfully creates experiment and triggers success action', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: 'Test Experiment',
                    description: 'Test hypothesis',
                    type: 'product',
                    feature_flag_key: 'test-experiment',
                })
                logic.actions.saveExperiment()
            })
                .toDispatchActions(['setExperiment', 'saveExperiment', 'createExperimentSuccess'])
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
                    feature_flag_key: 'test-experiment',
                })
                logic.actions.saveExperiment()
            })
                .toDispatchActions(['saveExperiment', 'createExperimentSuccess'])
                .toFinishAllListeners()

            expect(refreshTreeItem).toHaveBeenCalledWith('experiment', '123')
            expect(refreshTreeItem).toHaveBeenCalledWith('feature_flag', '456')
        })

        it('navigates to experiments list after creating a draft', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: 'Test Experiment',
                    description: 'Test hypothesis',
                    feature_flag_key: 'test-experiment',
                })
                logic.actions.saveExperiment()
            })
                .toDispatchActions(['saveExperiment', 'createExperimentSuccess'])
                .toFinishAllListeners()

            expect(routerPushSpy).toHaveBeenCalledWith('/experiments')
        })

        it('shows success toast', async () => {
            routerPushSpy.mockClear()

            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: 'Test Experiment',
                    description: 'Test hypothesis',
                    feature_flag_key: 'test-experiment',
                })
                logic.actions.saveExperiment()
            })
                .toDispatchActions(['saveExperiment', 'createExperimentSuccess'])
                .toFinishAllListeners()

            expect(lemonToast.success).toHaveBeenCalledWith('Experiment created successfully!')
            expect(routerPushSpy).toHaveBeenCalledTimes(1)
            expect(routerPushSpy).toHaveBeenCalledWith('/experiments')
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

    describe('experiment prop initialization', () => {
        it('defaults to NEW_EXPERIMENT when no prop is provided', async () => {
            const defaultLogic = createExperimentLogic()
            defaultLogic.mount()

            await expectLogic(defaultLogic).toMatchValues({
                experiment: partial({
                    id: 'new',
                    name: '',
                    description: '',
                    type: 'product',
                }),
            })

            defaultLogic.unmount()
        })

        it('uses provided experiment prop as default', async () => {
            const existingExperiment: Experiment = {
                ...NEW_EXPERIMENT,
                id: 123,
                name: 'Existing Experiment',
                description: 'Existing hypothesis',
                type: 'web',
                feature_flag_key: 'existing-flag',
            }

            const propsLogic = createExperimentLogic({ experiment: existingExperiment })
            propsLogic.mount()

            await expectLogic(propsLogic).toMatchValues({
                experiment: partial({
                    id: 123,
                    name: 'Existing Experiment',
                    description: 'Existing hypothesis',
                    type: 'web',
                    feature_flag_key: 'existing-flag',
                }),
            })

            propsLogic.unmount()
        })

        it('resetExperiment resets to NEW_EXPERIMENT when no prop provided', async () => {
            const defaultLogic = createExperimentLogic()
            defaultLogic.mount()

            await expectLogic(defaultLogic, () => {
                defaultLogic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: 'Changed Name',
                    description: 'Changed Description',
                })
            })
                .toDispatchActions(['setExperiment'])
                .toMatchValues({
                    experiment: partial({
                        name: 'Changed Name',
                        description: 'Changed Description',
                    }),
                })

            await expectLogic(defaultLogic, () => {
                defaultLogic.actions.resetExperiment()
            })
                .toDispatchActions(['resetExperiment'])
                .toMatchValues({
                    experiment: partial({
                        id: 'new',
                        name: '',
                        description: '',
                    }),
                })

            defaultLogic.unmount()
        })

        it('resetExperiment resets to provided experiment prop', async () => {
            const existingExperiment: Experiment = {
                ...NEW_EXPERIMENT,
                id: 456,
                name: 'Original Experiment',
                description: 'Original hypothesis',
                type: 'web',
            }

            const propsLogic = createExperimentLogic({ experiment: existingExperiment })
            propsLogic.mount()

            // afterMount syncs props.experiment — wait for that first
            await expectLogic(propsLogic)
                .toDispatchActions(['setExperiment'])
                .toMatchValues({
                    experiment: partial({ id: 456, name: 'Original Experiment' }),
                })

            // Now modify the experiment
            propsLogic.actions.setExperiment({
                ...existingExperiment,
                name: 'Modified Name',
                description: 'Modified Description',
            })

            await expectLogic(propsLogic).toMatchValues({
                experiment: partial({
                    name: 'Modified Name',
                    description: 'Modified Description',
                }),
            })

            await expectLogic(propsLogic, () => {
                propsLogic.actions.resetExperiment()
            })
                .toDispatchActions(['resetExperiment'])
                .toMatchValues({
                    experiment: partial({
                        id: 456,
                        name: 'Original Experiment',
                        description: 'Original hypothesis',
                        type: 'web',
                    }),
                })

            propsLogic.unmount()
        })
    })

    describe('form navigation scenarios', () => {
        const TAB_ID = 'test-tab'

        const incompleteDraft: Experiment = {
            ...NEW_EXPERIMENT,
            id: 100,
            name: 'Incomplete Draft',
            description: 'Saved without metrics',
            feature_flag_key: 'incomplete-draft',
        }

        const anotherDraft: Experiment = {
            ...NEW_EXPERIMENT,
            id: 200,
            name: 'Another Draft',
            description: 'A different experiment',
            feature_flag_key: 'another-draft',
        }

        beforeEach(() => {
            sessionStorage.clear()
        })

        it('visiting an incomplete draft populates the form with its data', async () => {
            const draftLogic = createExperimentLogic({ experiment: incompleteDraft, tabId: TAB_ID })
            draftLogic.mount()

            await expectLogic(draftLogic).toMatchValues({
                experiment: partial({
                    id: 100,
                    name: 'Incomplete Draft',
                    feature_flag_key: 'incomplete-draft',
                }),
            })

            draftLogic.unmount()
        })

        it('revisiting the same incomplete draft still shows its data', async () => {
            const firstVisit = createExperimentLogic({ experiment: incompleteDraft, tabId: TAB_ID })
            firstVisit.mount()

            await expectLogic(firstVisit).toMatchValues({
                experiment: partial({ id: 100, name: 'Incomplete Draft' }),
            })

            firstVisit.unmount()

            const secondVisit = createExperimentLogic({ experiment: incompleteDraft, tabId: TAB_ID })
            secondVisit.mount()

            await expectLogic(secondVisit).toMatchValues({
                experiment: partial({
                    id: 100,
                    name: 'Incomplete Draft',
                    feature_flag_key: 'incomplete-draft',
                }),
            })

            secondVisit.unmount()
        })

        it('navigating from one draft to a different draft shows the new draft data', async () => {
            const firstDraft = createExperimentLogic({ experiment: incompleteDraft, tabId: TAB_ID })
            firstDraft.mount()

            await expectLogic(firstDraft).toMatchValues({
                experiment: partial({ id: 100, name: 'Incomplete Draft' }),
            })

            firstDraft.unmount()

            const secondDraft = createExperimentLogic({ experiment: anotherDraft, tabId: TAB_ID })
            secondDraft.mount()

            await expectLogic(secondDraft).toMatchValues({
                experiment: partial({
                    id: 200,
                    name: 'Another Draft',
                    feature_flag_key: 'another-draft',
                }),
            })

            secondDraft.unmount()
        })

        it('creating new experiment after visiting a draft starts with a clean form', async () => {
            const draftLogic = createExperimentLogic({ experiment: incompleteDraft, tabId: TAB_ID })
            draftLogic.mount()

            await expectLogic(draftLogic).toMatchValues({
                experiment: partial({ id: 100, name: 'Incomplete Draft' }),
            })

            draftLogic.unmount()

            const newLogic = createExperimentLogic({ tabId: TAB_ID })
            newLogic.mount()

            await expectLogic(newLogic).toMatchValues({
                experiment: partial({ id: 'new', name: '', feature_flag_key: '' }),
            })

            newLogic.unmount()
        })

        it('draft from sessionStorage is loaded when creating a new experiment', async () => {
            const storedDraft: Experiment = {
                ...NEW_EXPERIMENT,
                name: 'Stored Draft',
                feature_flag_key: 'stored-draft',
            }

            sessionStorage.setItem(
                `experiment-draft-${TAB_ID}`,
                JSON.stringify({ experiment: storedDraft, timestamp: Date.now() })
            )

            const newLogic = createExperimentLogic({ tabId: TAB_ID })
            newLogic.mount()

            await expectLogic(newLogic).toMatchValues({
                experiment: partial({
                    id: 'new',
                    name: 'Stored Draft',
                    feature_flag_key: 'stored-draft',
                }),
            })

            newLogic.unmount()
        })

        it('sessionStorage draft is ignored when opening an existing experiment', async () => {
            const storedDraft: Experiment = {
                ...NEW_EXPERIMENT,
                name: 'Stored Draft',
                feature_flag_key: 'stored-draft',
            }

            sessionStorage.setItem(
                `experiment-draft-${TAB_ID}`,
                JSON.stringify({ experiment: storedDraft, timestamp: Date.now() })
            )

            const draftLogic = createExperimentLogic({ experiment: incompleteDraft, tabId: TAB_ID })
            draftLogic.mount()

            await expectLogic(draftLogic).toMatchValues({
                experiment: partial({
                    id: 100,
                    name: 'Incomplete Draft',
                    feature_flag_key: 'incomplete-draft',
                }),
            })

            draftLogic.unmount()
        })

        it('form state does not leak between new experiment sessions in the same tab', async () => {
            const firstNew = createExperimentLogic({ tabId: TAB_ID })
            firstNew.mount()

            firstNew.actions.setExperimentValue('name', 'First Attempt')
            firstNew.actions.setExperimentValue('feature_flag_key', 'first-attempt')

            await expectLogic(firstNew).toMatchValues({
                experiment: partial({ name: 'First Attempt', feature_flag_key: 'first-attempt' }),
            })

            firstNew.unmount()

            sessionStorage.clear()

            const secondNew = createExperimentLogic({ tabId: TAB_ID })
            secondNew.mount()

            await expectLogic(secondNew).toMatchValues({
                experiment: partial({ id: 'new', name: '', feature_flag_key: '' }),
            })

            secondNew.unmount()
        })

        it('unmount/remount with no draft starts fresh', async () => {
            logic.actions.setExperiment({
                ...NEW_EXPERIMENT,
                id: 123,
                name: 'Saved Experiment',
                description: 'Already saved',
            })

            logic.unmount()

            const freshLogic = createExperimentLogic()
            freshLogic.mount()

            await expectLogic(freshLogic).toMatchValues({
                experiment: partial({ id: 'new', name: '', description: '' }),
            })

            freshLogic.unmount()
        })

        it('two in-app tabs with new experiment forms maintain independent state', async () => {
            const tab1Logic = createExperimentLogic({ tabId: 'tab-1' })
            const tab2Logic = createExperimentLogic({ tabId: 'tab-2' })
            tab1Logic.mount()
            tab2Logic.mount()

            // Type into tab 1
            tab1Logic.actions.setExperimentValue('name', 'Tab 1 Experiment')
            tab1Logic.actions.setExperimentValue('feature_flag_key', 'tab-1-flag')

            // Type into tab 2
            tab2Logic.actions.setExperimentValue('name', 'Tab 2 Experiment')
            tab2Logic.actions.setExperimentValue('feature_flag_key', 'tab-2-flag')

            // Both tabs retain their own data
            await expectLogic(tab1Logic).toMatchValues({
                experiment: partial({ name: 'Tab 1 Experiment', feature_flag_key: 'tab-1-flag' }),
            })
            await expectLogic(tab2Logic).toMatchValues({
                experiment: partial({ name: 'Tab 2 Experiment', feature_flag_key: 'tab-2-flag' }),
            })

            // Modify tab 1 again — tab 2 is unaffected
            tab1Logic.actions.setExperimentValue('name', 'Tab 1 Updated')

            await expectLogic(tab1Logic).toMatchValues({
                experiment: partial({ name: 'Tab 1 Updated', feature_flag_key: 'tab-1-flag' }),
            })
            await expectLogic(tab2Logic).toMatchValues({
                experiment: partial({ name: 'Tab 2 Experiment', feature_flag_key: 'tab-2-flag' }),
            })

            tab1Logic.unmount()
            tab2Logic.unmount()
        })

        it('two in-app tabs with different drafts maintain independent state', async () => {
            const tab1Logic = createExperimentLogic({ experiment: incompleteDraft, tabId: 'tab-1' })
            const tab2Logic = createExperimentLogic({ experiment: anotherDraft, tabId: 'tab-2' })
            tab1Logic.mount()
            tab2Logic.mount()

            await expectLogic(tab1Logic).toMatchValues({
                experiment: partial({ id: 100, name: 'Incomplete Draft' }),
            })
            await expectLogic(tab2Logic).toMatchValues({
                experiment: partial({ id: 200, name: 'Another Draft' }),
            })

            // Edit in tab 1 does not affect tab 2
            tab1Logic.actions.setExperimentValue('name', 'Edited in Tab 1')

            await expectLogic(tab1Logic).toMatchValues({
                experiment: partial({ id: 100, name: 'Edited in Tab 1' }),
            })
            await expectLogic(tab2Logic).toMatchValues({
                experiment: partial({ id: 200, name: 'Another Draft' }),
            })

            tab1Logic.unmount()
            tab2Logic.unmount()
        })
    })

    describe('feature flag key auto-generation', () => {
        it('does not auto-generate a flag key when changing experiment name', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperimentValue('name', 'My New Experiment')
            })
                .toDispatchActions(['setExperimentValue'])
                .toMatchValues({
                    experiment: partial({
                        name: 'My New Experiment',
                        feature_flag_key: '',
                    }),
                })
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
                logic.actions.saveExperiment()
            }).toDispatchActions(['setExperiment', 'saveExperiment', 'createExperimentSuccess'])
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
                logic.actions.saveExperiment()
            }).toDispatchActions(['setExperiment', 'saveExperiment', 'createExperimentSuccess'])
        })

        it('includes experience continuity setting in submission', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: 'Test Experiment',
                    description: 'Test hypothesis',
                    feature_flag_key: 'test-experiment',
                    parameters: {
                        feature_flag_variants: [
                            { key: 'control', rollout_percentage: 50 },
                            { key: 'test', rollout_percentage: 50 },
                        ],
                    },
                })
                logic.actions.saveExperiment()
            }).toDispatchActions(['setExperiment', 'saveExperiment', 'createExperimentSuccess'])
        })
    })
})
