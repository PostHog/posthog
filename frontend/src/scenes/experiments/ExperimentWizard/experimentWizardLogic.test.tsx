import '@testing-library/jest-dom'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'
import { expectLogic, partial } from 'kea-test-utils'

import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { Experiment, FeatureFlagType } from '~/types'

import { VariantsPanel } from '../ExperimentForm/VariantsPanel'
import { createExperimentLogic } from '../ExperimentForm/createExperimentLogic'
import { selectExistingFeatureFlagModalLogic } from '../ExperimentForm/selectExistingFeatureFlagModalLogic'
import { variantsPanelLogic } from '../ExperimentForm/variantsPanelLogic'
import { NEW_EXPERIMENT } from '../constants'
import { experimentsLogic } from '../experimentsLogic'
import { experimentWizardLogic } from './experimentWizardLogic'
import { AboutStep } from './steps/AboutStep'

jest.mock('scenes/feature-flags/JSONEditorInput', () => ({
    JSONEditorInput: ({ onChange, value, placeholder, readOnly }: any) => (
        <input
            data-testid="json-editor-mock"
            value={value || ''}
            onChange={(e) => onChange?.(e.target.value)}
            placeholder={placeholder}
            readOnly={readOnly}
        />
    ),
}))

beforeAll(() => {
    const modalRoot = document.createElement('div')
    modalRoot.setAttribute('id', 'root')
    document.body.appendChild(modalRoot)
})

const TAB_ID = 'test-tab'

const mockEligibleFlags: Partial<FeatureFlagType>[] = [
    {
        id: 10,
        key: 'existing-flag',
        name: 'Existing Flag',
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
    },
    {
        id: 20,
        key: 'another-flag',
        name: 'Another Flag',
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
    },
]

const apiMocks = {
    get: {
        '/api/projects/@current/experiments/eligible_feature_flags/': () => [
            200,
            { results: mockEligibleFlags, count: mockEligibleFlags.length },
        ],
        '/api/projects/@current/feature_flags/': () => [200, { results: [], count: 0 }],
        '/api/projects/@current/experiments': () => [200, { results: [], count: 0 }],
    },
}

describe('experimentWizardLogic', () => {
    describe('linked feature flag sync between wizard and classic form', () => {
        describe('switching classic -> wizard', () => {
            let logic: ReturnType<typeof experimentWizardLogic.build>
            let createLogic: ReturnType<typeof createExperimentLogic.build>

            beforeEach(() => {
                localStorage.clear()
                sessionStorage.clear()
                useMocks(apiMocks)
                initKeaTests()

                featureFlagsLogic.mount()
                experimentsLogic.mount()

                createLogic = createExperimentLogic({ tabId: TAB_ID })
                createLogic.mount()
            })

            afterEach(() => {
                logic?.unmount()
                createLogic?.unmount()
                experimentsLogic.unmount()
                featureFlagsLogic.unmount()
            })

            it('auto-links when experiment feature_flag_key matches an eligible flag', async () => {
                createLogic.actions.setExperimentValue('feature_flag_key', 'existing-flag')

                logic = experimentWizardLogic({ tabId: TAB_ID })
                logic.mount()

                await expectLogic(logic)
                    .toDispatchActions(['resetWizard', 'loadFeatureFlagsForAutocomplete'])
                    .toDispatchActions(selectExistingFeatureFlagModalLogic, ['loadFeatureFlagsSuccess'])
                    .toDispatchActions(['setLinkedFeatureFlag', 'setFeatureFlagConfig'])
                    .toMatchValues({
                        linkedFeatureFlag: partial({ id: 10, key: 'existing-flag' }),
                    })
            })

            it('does not auto-link when feature_flag_key has no matching eligible flag', async () => {
                createLogic.actions.setExperimentValue('feature_flag_key', 'non-existent-flag')

                logic = experimentWizardLogic({ tabId: TAB_ID })
                logic.mount()

                await expectLogic(logic)
                    .toDispatchActions(['resetWizard', 'loadFeatureFlagsForAutocomplete'])
                    .toDispatchActions(selectExistingFeatureFlagModalLogic, ['loadFeatureFlagsSuccess'])
                    .toMatchValues({
                        linkedFeatureFlag: null,
                    })
            })

            it('does not auto-link when experiment has no feature_flag_key', async () => {
                logic = experimentWizardLogic({ tabId: TAB_ID })
                logic.mount()

                await expectLogic(logic)
                    .toDispatchActions(['resetWizard', 'loadFeatureFlagsForAutocomplete'])
                    .toDispatchActions(selectExistingFeatureFlagModalLogic, ['loadFeatureFlagsSuccess'])
                    .toMatchValues({
                        linkedFeatureFlag: null,
                    })
            })

            it('updates experiment variants when auto-linking a flag', async () => {
                createLogic.actions.setExperimentValue('feature_flag_key', 'another-flag')

                logic = experimentWizardLogic({ tabId: TAB_ID })
                logic.mount()

                await expectLogic(logic)
                    .toDispatchActions(selectExistingFeatureFlagModalLogic, ['loadFeatureFlagsSuccess'])
                    .toDispatchActions(['setLinkedFeatureFlag', 'setFeatureFlagConfig'])
                    .toMatchValues({
                        experiment: partial({
                            feature_flag_key: 'another-flag',
                            parameters: partial({
                                feature_flag_variants: [
                                    partial({ key: 'control', rollout_percentage: 33 }),
                                    partial({ key: 'variant-a', rollout_percentage: 33 }),
                                    partial({ key: 'variant-b', rollout_percentage: 34 }),
                                ],
                            }),
                        }),
                    })
            })

            it('resets linkedFeatureFlag to null on resetWizard', async () => {
                logic = experimentWizardLogic({ tabId: TAB_ID })
                logic.mount()

                logic.actions.setLinkedFeatureFlag(mockEligibleFlags[0] as any)
                await expectLogic(logic).toMatchValues({
                    linkedFeatureFlag: partial({ key: 'existing-flag' }),
                })

                logic.actions.resetWizard()
                await expectLogic(logic).toMatchValues({
                    linkedFeatureFlag: null,
                })
            })
        })

        describe('switching wizard -> classic', () => {
            const mockUpdateFeatureFlag = jest.fn()

            beforeEach(() => {
                useMocks(apiMocks)
                initKeaTests()
                jest.clearAllMocks()
            })

            afterEach(() => {
                cleanup()
            })

            it('auto-detects linked flag when experiment feature_flag_key matches an eligible flag', async () => {
                const experiment: Experiment = {
                    ...NEW_EXPERIMENT,
                    name: 'Test',
                    feature_flag_key: 'existing-flag',
                }

                render(<VariantsPanel experiment={experiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

                await waitFor(() => {
                    expect(screen.getByText('Linked feature flag')).toBeInTheDocument()
                })
            })

            it('stays in create mode when feature_flag_key has no matching eligible flag', async () => {
                const experiment: Experiment = {
                    ...NEW_EXPERIMENT,
                    name: 'Test',
                    feature_flag_key: 'brand-new-flag',
                }

                render(<VariantsPanel experiment={experiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

                await waitFor(() => {
                    expect(screen.getByText('Variant key')).toBeInTheDocument()
                })
                expect(screen.queryByText('Linked feature flag')).not.toBeInTheDocument()
            })

            it('shows linked flag variants from the matched flag', async () => {
                const experiment: Experiment = {
                    ...NEW_EXPERIMENT,
                    name: 'Test',
                    feature_flag_key: 'another-flag',
                }

                render(<VariantsPanel experiment={experiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

                await waitFor(() => {
                    expect(screen.getByText('Linked feature flag')).toBeInTheDocument()
                    expect(screen.getByText('control')).toBeInTheDocument()
                    expect(screen.getByText('variant-a')).toBeInTheDocument()
                    expect(screen.getByText('variant-b')).toBeInTheDocument()
                })
            })
        })
    })

    describe('feature flag input flow', () => {
        let logic: ReturnType<typeof experimentWizardLogic.build>
        let createLogic: ReturnType<typeof createExperimentLogic.build>

        beforeEach(() => {
            localStorage.clear()
            sessionStorage.clear()
            useMocks(apiMocks)
            initKeaTests()

            featureFlagsLogic.mount()
            experimentsLogic.mount()

            createLogic = createExperimentLogic({ tabId: TAB_ID })
            createLogic.mount()

            logic = experimentWizardLogic({ tabId: TAB_ID })
            logic.mount()
        })

        afterEach(() => {
            cleanup()
            logic?.unmount()
            createLogic?.unmount()
            experimentsLogic.unmount()
            featureFlagsLogic.unmount()
        })

        it('typing a name auto-generates the feature flag key with sanitization', async () => {
            render(
                <BindLogic logic={experimentWizardLogic} props={{ tabId: TAB_ID }}>
                    <AboutStep />
                </BindLogic>
            )

            const nameInput = screen.getByPlaceholderText('e.g., New checkout flow test')
            await userEvent.type(nameInput, 'My Cool Experiment')

            expect(screen.getByPlaceholderText('e.g., new-checkout-flow-test')).toHaveValue('my-cool-experiment')
        })

        it('selecting an existing flag sets key and variants from the flag', async () => {
            const flag = mockEligibleFlags[1] as FeatureFlagType

            logic.actions.setLinkedFeatureFlag(flag)
            logic.actions.setFeatureFlagConfig({
                feature_flag_key: flag.key,
                feature_flag_variants: flag.filters?.multivariate?.variants || [],
            })

            await expectLogic(logic).toMatchValues({
                linkedFeatureFlag: partial({ id: 20, key: 'another-flag' }),
                experiment: partial({
                    feature_flag_key: 'another-flag',
                    parameters: partial({
                        feature_flag_variants: [
                            partial({ key: 'control' }),
                            partial({ key: 'variant-a' }),
                            partial({ key: 'variant-b' }),
                        ],
                    }),
                }),
            })
        })

        it('removing a linked flag clears the key', async () => {
            logic.actions.setLinkedFeatureFlag(mockEligibleFlags[0] as FeatureFlagType)
            logic.actions.setFeatureFlagConfig({
                feature_flag_key: 'existing-flag',
                feature_flag_variants: mockEligibleFlags[0].filters?.multivariate?.variants || [],
            })

            // Now remove it (mirrors AboutStep onRemove handler)
            logic.actions.setLinkedFeatureFlag(null)
            logic.actions.setExperimentValue('feature_flag_key', '')
            logic.actions.clearFeatureFlagKeyValidation()

            await expectLogic(logic).toMatchValues({
                linkedFeatureFlag: null,
                experiment: partial({ feature_flag_key: '' }),
            })
        })
    })

    describe('step navigation', () => {
        let logic: ReturnType<typeof experimentWizardLogic.build>
        let createLogic: ReturnType<typeof createExperimentLogic.build>

        beforeEach(() => {
            localStorage.clear()
            sessionStorage.clear()
            useMocks(apiMocks)
            initKeaTests()

            featureFlagsLogic.mount()
            experimentsLogic.mount()

            createLogic = createExperimentLogic({ tabId: TAB_ID })
            createLogic.mount()

            logic = experimentWizardLogic({ tabId: TAB_ID })
            logic.mount()
        })

        afterEach(() => {
            logic?.unmount()
            createLogic?.unmount()
            experimentsLogic.unmount()
            featureFlagsLogic.unmount()
        })

        it.each([
            { target: 'about' as const, expectedStepNumber: 0 },
            { target: 'variants' as const, expectedStepNumber: 1 },
            { target: 'analytics' as const, expectedStepNumber: 2 },
        ])(
            'can jump directly to "$target" step (no gating / blocking of steps)',
            async ({ target, expectedStepNumber }) => {
                logic.actions.setStep(target)

                await expectLogic(logic).toMatchValues({
                    currentStep: target,
                    stepNumber: expectedStepNumber,
                })
            }
        )

        it('nextStep advances and prevStep goes back', async () => {
            expect(logic.values.currentStep).toBe('about')

            logic.actions.nextStep()
            await expectLogic(logic).toMatchValues({ currentStep: 'variants' })

            logic.actions.nextStep()
            await expectLogic(logic).toMatchValues({ currentStep: 'analytics' })

            logic.actions.prevStep()
            await expectLogic(logic).toMatchValues({ currentStep: 'variants' })
        })

        it('nextStep/prevStep stay same at end/beginning', async () => {
            logic.actions.setStep('analytics')
            logic.actions.nextStep()
            await expectLogic(logic).toMatchValues({ currentStep: 'analytics' })

            logic.actions.setStep('about')
            logic.actions.prevStep()
            await expectLogic(logic).toMatchValues({ currentStep: 'about' })
        })

        it('marks departing step when navigating away', async () => {
            logic.actions.nextStep()

            await expectLogic(logic).toMatchValues({
                departedSteps: { about: true },
            })
        })
    })

    describe('validation', () => {
        let logic: ReturnType<typeof experimentWizardLogic.build>
        let createLogic: ReturnType<typeof createExperimentLogic.build>

        beforeEach(() => {
            localStorage.clear()
            sessionStorage.clear()
            useMocks(apiMocks)
            initKeaTests()

            featureFlagsLogic.mount()
            experimentsLogic.mount()

            createLogic = createExperimentLogic({ tabId: TAB_ID })
            createLogic.mount()

            logic = experimentWizardLogic({ tabId: TAB_ID })
            logic.mount()
        })

        afterEach(() => {
            logic?.unmount()
            createLogic?.unmount()
            experimentsLogic.unmount()
            featureFlagsLogic.unmount()
        })

        it('shows no errors on initial load (before step departure)', async () => {
            await expectLogic(logic).toMatchValues({
                stepValidationErrors: { about: [], variants: [], analytics: [] },
            })
        })

        it('reveals required-field errors on about step after departure', async () => {
            // Before departure: no errors even though name/key are empty
            expect(logic.values.stepValidationErrors.about).toEqual([])

            // Depart the about step
            logic.actions.markStepDeparted('about')

            await expectLogic(logic).toMatchValues({
                stepValidationErrors: partial({
                    about: ['Name is required', 'Feature flag key is required'],
                }),
            })
        })

        it('variant split not summing to 100% triggers error on variants step', async () => {
            createLogic.actions.setExperiment({
                ...NEW_EXPERIMENT,
                parameters: {
                    feature_flag_variants: [
                        { key: 'control', rollout_percentage: 40 },
                        { key: 'test', rollout_percentage: 40 },
                    ],
                },
            })

            await expectLogic(logic).toMatchValues({
                stepValidationErrors: partial({
                    variants: ['Variant percentages must sum to 100%'],
                }),
            })
        })

        it.each([
            {
                desc: 'empty variant key',
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: '', rollout_percentage: 50 },
                ],
                expectedErrors: ['All variants must have a key'],
            },
            {
                desc: 'duplicate variant keys',
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'control', rollout_percentage: 50 },
                ],
                expectedErrors: ['Variant keys must be unique'],
            },
            {
                desc: 'valid variants',
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ],
                expectedErrors: [],
            },
        ])('variants step: $desc', async ({ variants, expectedErrors }) => {
            createLogic.actions.setExperiment({
                ...NEW_EXPERIMENT,
                parameters: { feature_flag_variants: variants },
            })

            await expectLogic(logic).toMatchValues({
                stepValidationErrors: partial({ variants: expectedErrors }),
            })
        })

        it('existing feature flag key shows error when validation fails', async () => {
            // Directly set the validation result on the variantsPanelLogic instance
            // (the same instance createExperimentLogic connects to)
            const vpLogic = variantsPanelLogic({ experiment: { ...NEW_EXPERIMENT }, disabled: false })
            vpLogic.actions.validateFeatureFlagKeySuccess({
                valid: false,
                error: 'A feature flag with this key already exists.',
            })

            await expectLogic(logic).toMatchValues({
                featureFlagKeyValidation: { valid: false, error: 'A feature flag with this key already exists.' },
                stepValidationErrors: partial({
                    about: ['A feature flag with this key already exists.'],
                }),
            })
        })

        it('saveExperiment marks all steps as departed, revealing all errors', async () => {
            // Experiment has empty name and key — errors hidden until departure
            expect(logic.values.stepValidationErrors.about).toEqual([])

            logic.actions.saveExperiment()

            await expectLogic(logic).toMatchValues({
                departedSteps: { about: true, variants: true, analytics: true },
                stepValidationErrors: partial({
                    about: ['Name is required', 'Feature flag key is required'],
                }),
            })
        })
    })

    describe('form submission', () => {
        let logic: ReturnType<typeof experimentWizardLogic.build>
        let createLogic: ReturnType<typeof createExperimentLogic.build>
        let capturedPayload: any

        beforeEach(() => {
            localStorage.clear()
            sessionStorage.clear()
            capturedPayload = null

            useMocks({
                ...apiMocks,
                post: {
                    '/api/projects/@current/experiments/': async (req: any) => {
                        capturedPayload = await req.json()
                        return [
                            200,
                            {
                                ...NEW_EXPERIMENT,
                                id: 42,
                                name: capturedPayload.name,
                                feature_flag_key: capturedPayload.feature_flag_key,
                                feature_flag: { id: 100, key: capturedPayload.feature_flag_key },
                            },
                        ]
                    },
                },
                patch: {
                    '/api/environments/@current/add_product_intent/': () => [200, {}],
                },
            })
            initKeaTests()

            featureFlagsLogic.mount()
            experimentsLogic.mount()

            createLogic = createExperimentLogic({ tabId: TAB_ID })
            createLogic.mount()

            logic = experimentWizardLogic({ tabId: TAB_ID })
            logic.mount()
        })

        afterEach(() => {
            logic?.unmount()
            createLogic?.unmount()
            experimentsLogic.unmount()
            featureFlagsLogic.unmount()
        })

        it('posts the experiment to the backend on save', async () => {
            createLogic.actions.setExperimentValue('name', 'Ship it')
            createLogic.actions.setExperimentValue('feature_flag_key', 'ship-it')

            logic.actions.saveExperiment()

            await waitFor(() => {
                expect(capturedPayload).not.toBeNull()
            })

            expect(capturedPayload).toMatchObject({
                name: 'Ship it',
                feature_flag_key: 'ship-it',
                parameters: expect.objectContaining({
                    feature_flag_variants: expect.arrayContaining([
                        expect.objectContaining({ key: 'control' }),
                        expect.objectContaining({ key: 'test' }),
                    ]),
                }),
            })
        })
    })
})
