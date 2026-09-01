import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { useMocks } from '~/mocks/jest'
import {
    type ExperimentExposureCriteria,
    NodeKind,
    ProductIntentContext,
    ProductKey,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { Experiment } from '~/types'

import { NEW_EXPERIMENT } from 'products/experiments/frontend/constants'
import { DEFAULT_MODEL, DEFAULT_PROVIDER } from 'products/replay_vision/frontend/replay_scanners/types'

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
    let scannerCreateSpy: jest.Mock
    let scannerRequestBody: Record<string, unknown> | null
    let productIntentBodies: Record<string, unknown>[]
    let exposureEventSeenWithSessionId: boolean

    beforeEach(() => {
        // Clear persisted state to prevent it from affecting tests
        localStorage.clear()
        sessionStorage.clear()
        scannerRequestBody = null
        productIntentBodies = []
        exposureEventSeenWithSessionId = true
        scannerCreateSpy = jest.fn(async ({ request }: { request: Request }) => {
            scannerRequestBody = (await request.json()) as Record<string, unknown>
            return [200, { id: 'scanner-123' }]
        })

        useMocks({
            get: {
                // saveExperiment verifies flag-key availability before building the payload
                '/api/projects/:team_id/feature_flags/': () => [200, { results: [], count: 0 }],
                '/api/projects/:team_id/experiments': () => [200, { results: [], count: 0 }],
                '/api/projects/:team_id/property_definitions/seen_together': ({ request }) => {
                    const eventNames = new URL(request.url).searchParams.getAll('event_names')
                    return [200, Object.fromEntries(eventNames.map((name) => [name, exposureEventSeenWithSessionId]))]
                },
            },
            post: {
                [`/api/projects/${MOCK_TEAM_ID}/experiments`]: async ({ request }) => {
                    const body = (await request.json()) as Experiment
                    if (!body.name || !body.description) {
                        return [400, { detail: 'Validation error' }]
                    }
                    return [
                        200,
                        {
                            ...body,
                            id: 123,
                            name: body.name,
                            description: body.description,
                            type: body.type || 'product',
                            feature_flag: {
                                ...body.feature_flag,
                                id: 456,
                                key: body.feature_flag_key,
                            },
                        },
                    ]
                },
                '/api/projects/:team_id/vision/scanners/': scannerCreateSpy,
            },
            patch: {
                '/api/environments/:team_id/add_product_intent/': async ({ request }) => {
                    productIntentBodies.push((await request.json()) as Record<string, unknown>)
                    return [200, {}]
                },
            },
        })
        initKeaTests()
        logic = createExperimentLogic()
        logic.mount()
        routerPushSpy = jest.spyOn(router.actions, 'push')
        jest.clearAllMocks()
    })

    afterEach(() => {
        if (logic.isMounted()) {
            logic.unmount()
        }
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

            expect(scannerCreateSpy).not.toHaveBeenCalled()
        })

        it('creates a scanner scoped to enrolled experiment sessions when selected', async () => {
            await expectLogic(logic, () => {
                logic.actions.setCreateReplayVisionScanner(true)
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: 'Checkout flow',
                    description: 'Test hypothesis',
                    feature_flag_key: 'checkout-flow',
                    feature_flag_config: {
                        filters: {
                            multivariate: {
                                variants: [
                                    { key: 'control', rollout_percentage: 50 },
                                    { key: 'new-checkout', rollout_percentage: 50 },
                                ],
                            },
                        },
                    },
                    exposure_criteria: {
                        filterTestAccounts: true,
                    },
                })
                logic.actions.saveExperiment()
            })
                .toDispatchActions(['saveExperiment', 'createExperimentSuccess'])
                .toFinishAllListeners()

            expect(scannerCreateSpy).toHaveBeenCalledTimes(1)
            expect(scannerRequestBody).toMatchObject({
                name: 'Checkout flow (#123)',
                scanner_type: 'classifier',
                // Enabling starts credit spend, so a created scanner must never arrive switched on
                enabled: false,
                // `model` is required by the create serializer — omitting it 400s every create
                provider: DEFAULT_PROVIDER,
                model: DEFAULT_MODEL,
                query: {
                    filter_test_accounts: true,
                    events: [
                        {
                            id: '$feature_flag_called',
                            properties: expect.arrayContaining([
                                expect.objectContaining({
                                    key: '$feature_flag_response',
                                    value: ['control', 'new-checkout'],
                                }),
                                expect.objectContaining({
                                    key: '$feature_flag',
                                    value: ['checkout-flow'],
                                }),
                            ]),
                        },
                    ],
                },
            })
            // A plain product intent is indistinguishable from someone reaching Replay Vision on their
            // own, so the cross-sell metadata is the only thing that attributes the scanner to experiments
            expect(productIntentBodies).toContainEqual(
                expect.objectContaining({
                    product_type: ProductKey.REPLAY_VISION,
                    intent_context: ProductIntentContext.EXPERIMENT_REPLAY_VISION_SCANNER_CREATED,
                    metadata: expect.objectContaining({
                        from: ProductKey.EXPERIMENTS,
                        to: ProductKey.REPLAY_VISION,
                        type: 'cross_sell',
                    }),
                })
            )
            expect(lemonToast.success).toHaveBeenCalledWith(
                'Experiment created. The Replay Vision scanner is off until you turn it on.',
                expect.objectContaining({
                    button: expect.objectContaining({ label: 'View scanner' }),
                })
            )
        })

        it.each([
            {
                name: 'falls back to the flag-value filter for a default exposure event',
                exposure_criteria: undefined,
                expectedQuery: {
                    properties: [expect.objectContaining({ key: '$feature/server-side-exposure', type: 'event' })],
                },
            },
            {
                name: 'keeps the custom exposure filter, never an unfiltered query',
                exposure_criteria: {
                    exposure_config: {
                        kind: NodeKind.ExperimentEventExposureConfig,
                        event: 'backend_assigned',
                        properties: [],
                    },
                } satisfies ExperimentExposureCriteria as ExperimentExposureCriteria,
                expectedQuery: {
                    events: [expect.objectContaining({ id: 'backend_assigned' })],
                },
            },
        ])(
            // The check reports "never seen with a session ID", which for a minutes-old flag is
            // mostly "never seen at all" — so it must never refuse, and must never leave the query
            // empty, which would scan every recording in the project.
            'creates a scoped scanner anyway when the exposure event looks unlinkable: $name',
            async ({ exposure_criteria, expectedQuery }) => {
                exposureEventSeenWithSessionId = false
                await expectLogic(logic, () => {
                    logic.actions.setCreateReplayVisionScanner(true)
                    logic.actions.setExperiment({
                        ...NEW_EXPERIMENT,
                        name: 'Server-side exposure',
                        description: 'Test hypothesis',
                        feature_flag_key: 'server-side-exposure',
                        ...(exposure_criteria ? { exposure_criteria } : {}),
                    })
                    logic.actions.saveExperiment()
                })
                    .toDispatchActions(['saveExperiment', 'createExperimentSuccess', 'saveExperimentSuccess'])
                    .toFinishAllListeners()

                expect(scannerCreateSpy).toHaveBeenCalledTimes(1)
                expect(scannerRequestBody).toMatchObject({ query: expect.objectContaining(expectedQuery) })
            }
        )

        it('keeps the created experiment when scanner creation fails', async () => {
            scannerCreateSpy.mockResolvedValueOnce([500, { detail: 'Scanner unavailable' }])
            await expectLogic(logic, () => {
                logic.actions.setCreateReplayVisionScanner(true)
                logic.actions.setExperiment({
                    ...NEW_EXPERIMENT,
                    name: 'Test Experiment',
                    description: 'Test hypothesis',
                    feature_flag_key: 'test-experiment',
                })
                logic.actions.saveExperiment()
            })
                .toDispatchActions(['saveExperiment', 'createExperimentSuccess', 'saveExperimentSuccess'])
                .toFinishAllListeners()

            expect(routerPushSpy).toHaveBeenCalledWith('/experiments/123')
            expect(lemonToast.error).toHaveBeenCalledWith(
                "Experiment created, but the Replay Vision scanner wasn't.",
                expect.objectContaining({
                    button: expect.objectContaining({ label: 'Set up scanner' }),
                })
            )
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

        it('setFeatureFlagConfig writes variants, rollout, and continuity into the draft flag config', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFeatureFlagConfig({
                    variants: [
                        { key: 'control', rollout_percentage: 33 },
                        { key: 'test', rollout_percentage: 33 },
                        { key: 'test-2', rollout_percentage: 34 },
                    ],
                    rollout_percentage: 80,
                    ensure_experience_continuity: true,
                })
            })
                .toDispatchActions(['setFeatureFlagConfig'])
                .toMatchValues({
                    experiment: partial({
                        feature_flag_config: {
                            filters: {
                                multivariate: {
                                    variants: [
                                        { key: 'control', rollout_percentage: 33 },
                                        { key: 'test', rollout_percentage: 33 },
                                        { key: 'test-2', rollout_percentage: 34 },
                                    ],
                                },
                                groups: [{ properties: [], rollout_percentage: 80 }],
                            },
                            ensure_experience_continuity: true,
                        },
                    }),
                })

            expect(logic.values.experiment.feature_flag_config?.filters?.multivariate?.variants).toHaveLength(3)
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
        beforeEach(() => {
            sessionStorage.clear()
            // Fully unmount the shared singleton so each test controls the
            // mount lifecycle and afterMount/beforeUnmount fire as expected.
            logic.unmount()
        })

        it('abandoning the form and coming back starts fresh', async () => {
            const firstNew = createExperimentLogic()
            firstNew.mount()

            firstNew.actions.setExperimentValue('name', 'First Attempt')
            firstNew.actions.setExperimentValue('feature_flag_key', 'first-attempt')
            firstNew.actions.setCreateReplayVisionScanner(true)

            await expectLogic(firstNew).toMatchValues({
                experiment: partial({ name: 'First Attempt', feature_flag_key: 'first-attempt' }),
                createReplayVisionScanner: true,
            })

            // User navigates away — no save
            firstNew.unmount()

            const secondNew = createExperimentLogic()
            secondNew.mount()

            await expectLogic(secondNew).toMatchValues({
                experiment: partial({ id: 'new', name: '', feature_flag_key: '' }),
                createReplayVisionScanner: false,
            })

            secondNew.unmount()
        })
    })

    describe('post-save state reset', () => {
        beforeEach(() => {
            sessionStorage.clear()
            // Fully unmount the shared singleton so each test controls the
            // mount lifecycle and afterMount/beforeUnmount fire as expected.
            logic.unmount()
        })

        it('form resets to NEW_EXPERIMENT after saving and re-entering create mode', async () => {
            const firstLogic = createExperimentLogic()
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
            const secondLogic = createExperimentLogic()
            secondLogic.mount()

            await expectLogic(secondLogic).toMatchValues({
                experiment: partial({ id: 'new', name: '', feature_flag_key: '' }),
            })

            secondLogic.unmount()
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
                    feature_flag_config: {
                        filters: {
                            multivariate: {
                                variants: [
                                    { key: 'control', rollout_percentage: 50 },
                                    { key: 'treatment', rollout_percentage: 50 },
                                ],
                            },
                        },
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
                    feature_flag_config: {
                        filters: {
                            multivariate: {
                                variants: [
                                    { key: 'control', rollout_percentage: 50 },
                                    { key: 'test', rollout_percentage: 50 },
                                ],
                            },
                        },
                        ensure_experience_continuity: true,
                    },
                })
                logic.actions.saveExperiment()
            }).toDispatchActions(['setExperiment', 'saveExperiment', 'createExperimentSuccess'])
        })
    })
})
