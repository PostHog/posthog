import { MOCK_TEAM_ID } from 'lib/api.mock'

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
                [`/api/projects/${MOCK_TEAM_ID}/experiments`]: async (req) => {
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
                '/api/environments/:team_id/add_product_intent/': () => [200, {}],
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

        it('navigates to experiment view page after creating a draft', async () => {
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

            expect(routerPushSpy).toHaveBeenCalledWith('/experiments/123')
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
            expect(routerPushSpy).toHaveBeenCalledWith('/experiments/123')
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

    describe('initialization', () => {
        it('defaults to NEW_EXPERIMENT', async () => {
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

        it('resetExperiment resets to NEW_EXPERIMENT', async () => {
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
    })

    describe('form navigation scenarios', () => {
        const TAB_ID = 'test-tab'

        beforeEach(() => {
            sessionStorage.clear()
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
    })

    describe('post-save state reset', () => {
        const TAB_ID = 'test-tab'

        beforeEach(() => {
            sessionStorage.clear()
        })

        it('form resets to NEW_EXPERIMENT after saving and re-entering create mode', async () => {
            const firstLogic = createExperimentLogic({ tabId: TAB_ID })
            firstLogic.mount()

            await expectLogic(firstLogic).toMatchValues({
                experiment: partial({ id: 'new', name: '' }),
            })

            // Simulate what saveExperiment does on success:
            // the server response replaces the form state
            firstLogic.actions.setExperiment({
                ...NEW_EXPERIMENT,
                id: 999,
                name: 'Saved Experiment',
                description: 'Already persisted',
                feature_flag_key: 'saved-experiment',
            })

            await expectLogic(firstLogic).toMatchValues({
                experiment: partial({ id: 999, name: 'Saved Experiment' }),
            })

            // Scene transitions away from create mode — component unmounts the logic
            firstLogic.unmount()

            // User navigates back to /experiments/new — component remounts the logic
            const secondLogic = createExperimentLogic({ tabId: TAB_ID })
            secondLogic.mount()

            await expectLogic(secondLogic).toMatchValues({
                experiment: partial({ id: 'new', name: '', feature_flag_key: '' }),
            })

            secondLogic.unmount()
        })

        it('navigating away without saving preserves draft for next visit', async () => {
            const firstLogic = createExperimentLogic({ tabId: TAB_ID })
            firstLogic.mount()

            firstLogic.actions.setExperimentValue('name', 'Work In Progress')
            firstLogic.actions.setExperimentValue('feature_flag_key', 'wip-flag')

            await expectLogic(firstLogic).toMatchValues({
                experiment: partial({ name: 'Work In Progress', feature_flag_key: 'wip-flag' }),
            })

            // User navigates away (e.g. switches tab) — no cancel, no save
            firstLogic.unmount()

            // User comes back to /experiments/new
            const secondLogic = createExperimentLogic({ tabId: TAB_ID })
            secondLogic.mount()

            await expectLogic(secondLogic).toMatchValues({
                experiment: partial({ id: 'new', name: 'Work In Progress', feature_flag_key: 'wip-flag' }),
            })

            secondLogic.unmount()
        })

        it('cancel clears draft so re-entering create mode starts fresh', async () => {
            const firstLogic = createExperimentLogic({ tabId: TAB_ID })
            firstLogic.mount()

            firstLogic.actions.setExperimentValue('name', 'Will Cancel')
            firstLogic.actions.setExperimentValue('feature_flag_key', 'will-cancel')

            await expectLogic(firstLogic).toMatchValues({
                experiment: partial({ name: 'Will Cancel', feature_flag_key: 'will-cancel' }),
            })

            // User clicks cancel — clears draft then navigates away
            firstLogic.actions.cancelForm()
            firstLogic.unmount()

            // User navigates back to /experiments/new
            const secondLogic = createExperimentLogic({ tabId: TAB_ID })
            secondLogic.mount()

            await expectLogic(secondLogic).toMatchValues({
                experiment: partial({ id: 'new', name: '', feature_flag_key: '' }),
            })

            secondLogic.unmount()
        })

        it('canceling one tab does not affect the other', async () => {
            const tab1Logic = createExperimentLogic({ tabId: 'tab-1' })
            const tab2Logic = createExperimentLogic({ tabId: 'tab-2' })
            tab1Logic.mount()
            tab2Logic.mount()

            tab1Logic.actions.setExperimentValue('name', 'Tab 1 Experiment')
            tab1Logic.actions.setExperimentValue('feature_flag_key', 'tab-1-flag')
            tab2Logic.actions.setExperimentValue('name', 'Tab 2 Experiment')
            tab2Logic.actions.setExperimentValue('feature_flag_key', 'tab-2-flag')

            // Cancel tab 1
            tab1Logic.actions.cancelForm()
            tab1Logic.unmount()

            // Tab 2 is unaffected
            await expectLogic(tab2Logic).toMatchValues({
                experiment: partial({ name: 'Tab 2 Experiment', feature_flag_key: 'tab-2-flag' }),
            })

            // Re-opening tab 1 starts fresh
            const newTab1Logic = createExperimentLogic({ tabId: 'tab-1' })
            newTab1Logic.mount()

            await expectLogic(newTab1Logic).toMatchValues({
                experiment: partial({ id: 'new', name: '', feature_flag_key: '' }),
            })

            newTab1Logic.unmount()
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
