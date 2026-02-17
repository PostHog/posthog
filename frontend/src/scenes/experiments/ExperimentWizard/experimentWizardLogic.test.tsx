import '@testing-library/jest-dom'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { expectLogic, partial } from 'kea-test-utils'

import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { Experiment } from '~/types'

import { VariantsPanel } from '../ExperimentForm/VariantsPanel'
import { createExperimentLogic } from '../ExperimentForm/createExperimentLogic'
import { selectExistingFeatureFlagModalLogic } from '../ExperimentForm/selectExistingFeatureFlagModalLogic'
import { NEW_EXPERIMENT } from '../constants'
import { experimentsLogic } from '../experimentsLogic'
import { experimentWizardLogic } from './experimentWizardLogic'

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

const mockEligibleFlags = [
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

describe('guide panel localStorage persistence', () => {
    let logic: ReturnType<typeof experimentWizardLogic.build>

    beforeEach(() => {
        localStorage.clear()
        useMocks(apiMocks)
        initKeaTests()

        featureFlagsLogic.mount()
        experimentsLogic.mount()
        createExperimentLogic({ tabId: TAB_ID }).mount()
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

        logic = experimentWizardLogic({ tabId: TAB_ID })
        logic.mount()

        await expectLogic(logic).toMatchValues({ showGuide: expected })
    })

    it('persists to localStorage when toggled', async () => {
        logic = experimentWizardLogic({ tabId: TAB_ID })
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

describe('linked feature flag sync between wizard and classic form', () => {
    describe('switching classic -> wizard', () => {
        let logic: ReturnType<typeof experimentWizardLogic.build>
        let createLogic: ReturnType<typeof createExperimentLogic.build>

        beforeEach(() => {
            localStorage.clear()
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
