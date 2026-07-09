import { MOCK_TEAM_ID } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'
import { expectLogic, partial } from 'kea-test-utils'

import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { FeatureFlagType } from '~/types'

import { NEW_EXPERIMENT } from '../constants'
import { createExperimentLogic } from '../ExperimentForm/createExperimentLogic'
import { variantsPanelLogic } from '../ExperimentForm/variantsPanelLogic'
import { experimentsLogic } from '../experimentsLogic'
import { experimentWizardLogic, stepStorageKey } from './experimentWizardLogic'
import { AboutStep } from './steps/AboutStep'
import { VariantsStep } from './steps/VariantsStep'

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
        '/api/projects/:team_id/experiments/eligible_feature_flags/': () => [
            200,
            { results: mockEligibleFlags, count: mockEligibleFlags.length },
        ],
        '/api/projects/:team_id/feature_flags/': () => [200, { results: [], count: 0 }],
        '/api/projects/:team_id/experiments': () => [200, { results: [], count: 0 }],
    },
}

describe('guide panel localStorage persistence', () => {
    let logic: ReturnType<typeof experimentWizardLogic.build>

    beforeEach(() => {
        localStorage.clear()
        useMocks(apiMocks)
        initKeaTests()

        featureFlagsLogic.mount()
        experimentsLogic.mount()
        createExperimentLogic().mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        { stored: null, expected: true, label: 'defaults to true when nothing stored' },
        { stored: 'true', expected: true, label: 'reads true from localStorage' },
        { stored: 'false', expected: false, label: 'reads false from localStorage' },
        { stored: 'other', expected: false, label: 'treats non-true strings as false' },
    ])('$label', async ({ stored, expected }) => {
        if (stored !== null) {
            localStorage.setItem('experiment-wizard-show-guide', stored)
        }

        logic = experimentWizardLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({ showGuide: expected })
    })

    it('persists to localStorage when toggled', async () => {
        logic = experimentWizardLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({ showGuide: true })

        logic.actions.toggleGuide()
        await expectLogic(logic).toMatchValues({ showGuide: false })
        expect(localStorage.getItem('experiment-wizard-show-guide')).toEqual('false')

        logic.actions.toggleGuide()
        await expectLogic(logic).toMatchValues({ showGuide: true })
        expect(localStorage.getItem('experiment-wizard-show-guide')).toEqual('true')
    })
})

describe('experimentWizardLogic', () => {
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

            createLogic = createExperimentLogic()
            createLogic.mount()

            logic = experimentWizardLogic()
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
                <BindLogic logic={experimentWizardLogic} props={{}}>
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

        it('shows "Use this flag" button when feature flag key already exists', async () => {
            // Set validation result with existingFlag BEFORE rendering
            const vpLogic = variantsPanelLogic({ experiment: { ...NEW_EXPERIMENT }, disabled: false })
            vpLogic.actions.validateFeatureFlagKeySuccess({
                valid: false,
                error: 'A feature flag with this key already exists.',
                key: 'existing-flag',
                existingFlag: mockEligibleFlags[0] as FeatureFlagType,
            })

            // Wait for the value to propagate through the kea connection chain
            await expectLogic(logic).toMatchValues({
                featureFlagKeyValidation: partial({
                    valid: false,
                    existingFlag: partial({ id: 10 }),
                }),
            })

            render(
                <BindLogic logic={experimentWizardLogic} props={{}}>
                    <AboutStep />
                </BindLogic>
            )

            await waitFor(() => {
                expect(screen.getByText('A feature flag with this key already exists.')).toBeInTheDocument()
                expect(screen.getByText('Use this flag')).toBeInTheDocument()
            })
        })

        it('clicking "Use this flag" links the existing flag', async () => {
            const flag = mockEligibleFlags[0] as FeatureFlagType

            // Set validation result with existingFlag BEFORE rendering
            const vpLogic = variantsPanelLogic({ experiment: { ...NEW_EXPERIMENT }, disabled: false })
            vpLogic.actions.validateFeatureFlagKeySuccess({
                valid: false,
                error: 'A feature flag with this key already exists.',
                key: 'existing-flag',
                existingFlag: flag,
            })

            await expectLogic(logic).toMatchValues({
                featureFlagKeyValidation: partial({
                    valid: false,
                    existingFlag: partial({ id: 10 }),
                }),
            })

            render(
                <BindLogic logic={experimentWizardLogic} props={{}}>
                    <AboutStep />
                </BindLogic>
            )

            await waitFor(() => {
                expect(screen.getByText('Use this flag')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByText('Use this flag'))

            await expectLogic(logic).toMatchValues({
                linkedFeatureFlag: partial({ id: 10, key: 'existing-flag' }),
                experiment: partial({
                    feature_flag_key: 'existing-flag',
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

            createLogic = createExperimentLogic()
            createLogic.mount()

            logic = experimentWizardLogic()
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

        it('preserves current step across unmount/remount', async () => {
            logic.actions.nextStep()
            await expectLogic(logic).toMatchValues({ currentStep: 'variants' })

            logic.unmount()
            createLogic.unmount()

            createLogic = createExperimentLogic()
            createLogic.mount()
            logic = experimentWizardLogic()
            logic.mount()

            await expectLogic(logic).toMatchValues({ currentStep: 'variants' })
        })

        it('wizard logic is a singleton that shares step state', async () => {
            const wizardLogicA = experimentWizardLogic()
            wizardLogicA.mount()
            const wizardLogicB = experimentWizardLogic()
            wizardLogicB.mount()

            wizardLogicA.actions.setStep('variants')

            // Both references resolve to the same singleton instance
            await expectLogic(wizardLogicA).toMatchValues({ currentStep: 'variants' })
            await expectLogic(wizardLogicB).toMatchValues({ currentStep: 'variants' })

            wizardLogicB.actions.setStep('analytics')

            await expectLogic(wizardLogicA).toMatchValues({ currentStep: 'analytics' })
            await expectLogic(wizardLogicB).toMatchValues({ currentStep: 'analytics' })

            wizardLogicA.unmount()
            wizardLogicB.unmount()
        })

        it('resets step to about on saveExperimentSuccess', async () => {
            logic.actions.setStep('analytics')
            await expectLogic(logic).toMatchValues({ currentStep: 'analytics' })

            logic.actions.saveExperimentSuccess()

            await expectLogic(logic).toMatchValues({
                currentStep: 'about',
                linkedFeatureFlag: null,
                departedSteps: {},
            })
            expect(sessionStorage.getItem(stepStorageKey())).toBeNull()
        })

        it('clears sessionStorage step on saveExperimentSuccess so remount starts fresh', async () => {
            logic.actions.setStep('analytics')
            expect(sessionStorage.getItem(stepStorageKey())).toBe('analytics')

            logic.actions.saveExperimentSuccess()
            logic.unmount()
            createLogic.unmount()

            createLogic = createExperimentLogic()
            createLogic.mount()
            logic = experimentWizardLogic()
            logic.mount()

            await expectLogic(logic).toMatchValues({ currentStep: 'about' })
        })

        it('stale sessionStorage from previous session is cleared on fresh navigation', () => {
            // Simulate stale state: step saved from a previous experiment session
            sessionStorage.setItem(stepStorageKey(), 'analytics')

            // Simulate what experimentSceneLogic does on fresh navigation to /experiments/new
            sessionStorage.removeItem(stepStorageKey())

            // Now mount the wizard — should start on 'about'
            logic.unmount()
            createLogic.unmount()

            createLogic = createExperimentLogic()
            createLogic.mount()
            logic = experimentWizardLogic()
            logic.mount()

            expect(logic.values.currentStep).toBe('about')
        })

        it('remount preserves step when sessionStorage is not cleared', async () => {
            logic.actions.setStep('variants')
            await expectLogic(logic).toMatchValues({ currentStep: 'variants' })

            // Unmount and remount without clearing sessionStorage
            logic.unmount()
            createLogic.unmount()

            createLogic = createExperimentLogic()
            createLogic.mount()
            logic = experimentWizardLogic()
            logic.mount()

            await expectLogic(logic).toMatchValues({ currentStep: 'variants' })
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

            createLogic = createExperimentLogic()
            createLogic.mount()

            logic = experimentWizardLogic()
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
                key: 'existing-flag',
            })

            await expectLogic(logic).toMatchValues({
                featureFlagKeyValidation: {
                    valid: false,
                    error: 'A feature flag with this key already exists.',
                    key: 'existing-flag',
                },
                stepValidationErrors: partial({
                    about: ['A feature flag with this key already exists.'],
                }),
            })
        })

        it('feature flag key is re-validated on remount', async () => {
            // Set up: trigger a duplicate-key validation error
            const vpLogic = variantsPanelLogic({ experiment: { ...NEW_EXPERIMENT }, disabled: false })
            createLogic.actions.setExperimentValue('feature_flag_key', 'existing-flag')
            vpLogic.actions.validateFeatureFlagKeySuccess({
                valid: false,
                error: 'A feature flag with this key already exists.',
                key: 'existing-flag',
            })

            await expectLogic(logic).toMatchValues({
                featureFlagKeyValidation: partial({
                    valid: false,
                    error: 'A feature flag with this key already exists.',
                }),
            })

            // Unmount and remount
            logic.unmount()
            vpLogic.unmount()
            createLogic.unmount()

            createLogic = createExperimentLogic()
            createLogic.mount()
            logic = experimentWizardLogic()
            logic.mount()

            // afterMount should re-validate since feature_flag_key is set
            await expectLogic(logic).toDispatchActions(['validateFeatureFlagKey'])
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
                    [`/api/projects/${MOCK_TEAM_ID}/experiments/`]: async ({ request }) => {
                        capturedPayload = (await request.json()) as Record<string, any>
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
                    '/api/environments/:team_id/add_product_intent/': () => [200, {}],
                },
            })
            initKeaTests()

            featureFlagsLogic.mount()
            experimentsLogic.mount()

            createLogic = createExperimentLogic()
            createLogic.mount()

            logic = experimentWizardLogic()
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
            // The About step validates the key as the user types; a confirmed-available key is
            // what makes the save send the flag config (via the feature_flag object).
            logic.actions.validateFeatureFlagKey('ship-it')
            await waitFor(() => {
                expect(createLogic.values.featureFlagKeyValidation).toMatchObject({ valid: true })
            })

            logic.actions.saveExperiment()

            await waitFor(() => {
                expect(capturedPayload).not.toBeNull()
            })

            expect(capturedPayload).toMatchObject({
                name: 'Ship it',
                feature_flag_key: 'ship-it',
                feature_flag: {
                    filters: expect.objectContaining({
                        multivariate: {
                            variants: expect.arrayContaining([
                                expect.objectContaining({ key: 'control' }),
                                expect.objectContaining({ key: 'test' }),
                            ]),
                        },
                    }),
                },
            })
            // Flag config no longer travels through the deprecated parameters keys.
            expect(capturedPayload.parameters).not.toHaveProperty('feature_flag_variants')
        })
    })

    describe('VariantsStep with linked feature flag', () => {
        let logic: ReturnType<typeof experimentWizardLogic.build>
        let createLogic: ReturnType<typeof createExperimentLogic.build>

        beforeEach(() => {
            localStorage.clear()
            sessionStorage.clear()
            useMocks(apiMocks)
            initKeaTests()

            featureFlagsLogic.mount()
            experimentsLogic.mount()

            createLogic = createExperimentLogic()
            createLogic.mount()

            logic = experimentWizardLogic()
            logic.mount()
        })

        afterEach(() => {
            cleanup()
            logic?.unmount()
            createLogic?.unmount()
            experimentsLogic.unmount()
            featureFlagsLogic.unmount()
        })

        const renderVariantsStep = (): void => {
            render(
                <BindLogic logic={experimentWizardLogic} props={{}}>
                    <VariantsStep />
                </BindLogic>
            )
        }

        const makeFlagWithVariantsAndRollout = (
            variants: Array<{ key: string; rollout_percentage: number }>,
            rolloutPercentage: number
        ): Partial<FeatureFlagType> => ({
            ...mockEligibleFlags[0],
            filters: {
                groups: [{ properties: [], rollout_percentage: rolloutPercentage }],
                multivariate: { variants },
            },
        })

        it('shows read-only banner when a linked flag is set', () => {
            logic.actions.setLinkedFeatureFlag(mockEligibleFlags[0] as FeatureFlagType)

            renderVariantsStep()

            expect(screen.getByText(/For linked feature flags, this step is read-only/)).toBeInTheDocument()
        })

        it.each([
            {
                desc: '2 variants with 50/50 split at 100% rollout',
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ],
                rollout: 100,
                expectedKeys: ['control', 'test'],
            },
            {
                desc: '3 variants with uneven split at 80% rollout',
                variants: [
                    { key: 'control', rollout_percentage: 34 },
                    { key: 'variant-a', rollout_percentage: 33 },
                    { key: 'variant-b', rollout_percentage: 33 },
                ],
                rollout: 80,
                expectedKeys: ['control', 'variant-a', 'variant-b'],
            },
        ])('displays variant keys and rollout for $desc', ({ variants, rollout, expectedKeys }) => {
            const flag = makeFlagWithVariantsAndRollout(variants, rollout)
            logic.actions.setLinkedFeatureFlag(flag as FeatureFlagType)

            renderVariantsStep()

            for (const key of expectedKeys) {
                expect(screen.getByText(key)).toBeInTheDocument()
            }
            expect(screen.getByText(`${rollout}%`)).toBeInTheDocument()
        })

        it('defaults rollout to 100% when groups have no rollout_percentage', () => {
            const flag: Partial<FeatureFlagType> = {
                ...mockEligibleFlags[0],
                filters: {
                    groups: [{ properties: [] }],
                    multivariate: {
                        variants: [
                            { key: 'control', rollout_percentage: 50 },
                            { key: 'test', rollout_percentage: 50 },
                        ],
                    },
                },
            }
            logic.actions.setLinkedFeatureFlag(flag as FeatureFlagType)

            renderVariantsStep()

            expect(screen.getByText('100%')).toBeInTheDocument()
        })

        it('does not show read-only banner when no linked flag is set', () => {
            renderVariantsStep()

            expect(screen.queryByText(/For linked feature flags, this step is read-only/)).not.toBeInTheDocument()
        })
    })

    describe('auto-link guard against the shared flag-load singleton', () => {
        let createLogic: ReturnType<typeof createExperimentLogic.build>
        let logic: ReturnType<typeof experimentWizardLogic.build>

        beforeEach(() => {
            localStorage.clear()
            sessionStorage.clear()
            useMocks(apiMocks)
            initKeaTests()

            featureFlagsLogic.mount()
            experimentsLogic.mount()

            createLogic = createExperimentLogic()
            createLogic.mount()
            logic = experimentWizardLogic()
            logic.mount()
        })

        afterEach(() => {
            logic?.unmount()
            createLogic?.unmount()
            experimentsLogic.unmount()
            featureFlagsLogic.unmount()
        })

        it('a later flag load does not auto-link once the initial check is done', async () => {
            // afterMount fires loadFeatureFlagsForAutocomplete; wait for the first
            // success to mark the initial check done before a matching key is set.
            await expectLogic(logic).toDispatchActions(['loadFeatureFlagsSuccess']).toMatchValues({
                initialFlagCheckDone: true,
            })

            createLogic.actions.setExperimentValue('feature_flag_key', 'existing-flag')

            // A subsequent flag load (e.g. from the shared selectExistingFeatureFlagModalLogic)
            // must not retroactively auto-link the now-matching key.
            await expectLogic(logic, () => {
                logic.actions.loadFeatureFlagsForAutocomplete()
            }).toDispatchActions(['loadFeatureFlagsSuccess'])

            await expectLogic(logic).toMatchValues({
                linkedFeatureFlag: null,
            })
        })
    })
})
