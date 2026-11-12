import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useAsyncActions, useValues } from 'kea'

import { toast } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { FeaturePreviews, FeaturePreviewsComingSoon } from './FeaturePreviews'
import { EnrichedEarlyAccessFeature, featurePreviewsLogic } from './featurePreviewsLogic'

jest.mock('posthog-js')

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
    useAsyncActions: jest.fn(),
}))

jest.mock('lib/hooks/useAnchor', () => ({
    useAnchor: jest.fn(),
}))

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: jest.fn(),
}))

jest.mock('@posthog/quill', () => ({
    ...jest.requireActual('@posthog/quill'),
    toast: { success: jest.fn() },
}))

jest.mock('lib/components/Cards/BasicCard', () => ({
    BasicCard: ({ children }: { children: React.ReactNode }) => <div data-attr="basic-card">{children}</div>,
}))

const mockedUseValues = useValues as jest.Mock
const mockedUseActions = useActions as jest.Mock
const mockedUseAsyncActions = useAsyncActions as jest.Mock
const mockedUseFeatureFlag = useFeatureFlag as jest.Mock

const BETA_FEATURE: EnrichedEarlyAccessFeature = {
    flagKey: 'customer-analytics-roadmap',
    name: 'Customer analytics',
    description: 'Get context about your customers.',
    stage: 'beta',
    enabled: false,
    documentationUrl: '',
    payload: undefined,
}

const CONCEPT_FEATURE: EnrichedEarlyAccessFeature = { ...BETA_FEATURE, flagKey: 'some-concept', stage: 'concept' }

const BANNER_TEXT = /controlled by the PERSISTED_FEATURE_FLAGS environment variable, not the toggles below/

function setupMocks({
    cloud = true,
    isDebug = false,
    features = [BETA_FEATURE],
    searchTerm = '',
}: { cloud?: boolean; isDebug?: boolean; features?: EnrichedEarlyAccessFeature[]; searchTerm?: string } = {}): void {
    mockedUseValues.mockImplementation((logic: unknown) => {
        if (logic === featurePreviewsLogic) {
            return {
                filteredEarlyAccessFeatures: features,
                activePreviewFeatures: features.filter((f) => f.stage === 'beta' || f.stage === 'alpha'),
                conceptPreviewFeatures: features.filter((f) => f.stage === 'concept'),
                shouldShowEmptyState: features.length === 0,
                rawEarlyAccessFeaturesLoading: false,
                searchTerm,
                activeFeedbackFlagKey: null,
                activeFeedbackFlagKeyLoading: false,
            }
        }
        if (logic === userLogic) {
            return { hasAvailableFeature: () => true }
        }
        if (logic === preflightLogic) {
            return { preflight: { cloud, is_debug: isDebug } }
        }
        return {}
    })

    mockedUseActions.mockImplementation(() => ({
        loadEarlyAccessFeatures: jest.fn(),
        setSearchTerm: jest.fn(),
        beginEarlyAccessFeatureFeedback: jest.fn(),
        cancelEarlyAccessFeatureFeedback: jest.fn(),
        updateEarlyAccessFeatureEnrollment: jest.fn(),
        copyExternalFeaturePreviewLink: jest.fn(),
    }))

    mockedUseAsyncActions.mockImplementation(() => ({
        submitEarlyAccessFeatureFeedback: jest.fn(),
    }))
}

describe('FeaturePreviews', () => {
    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
    })

    describe.each([
        ['the Lemon page', false],
        ['the quill page', true],
    ])('on %s', (_, todayRailNav) => {
        beforeEach(() => {
            mockedUseFeatureFlag.mockReturnValue(todayRailNav)
        })

        test.each([
            [false, false, false],
            [true, false, true],
            [false, true, true],
        ])('with cloud=%s and is_debug=%s the toggle switch is enabled: %s', (cloud, isDebug, expectedEnabled) => {
            setupMocks({ cloud, isDebug })

            render(<FeaturePreviews />)

            // The quill Switch is a span, so it reports disabled through aria-disabled
            const toggle = screen.getByRole('switch')
            const disabled = toggle.hasAttribute('disabled') || toggle.getAttribute('aria-disabled') === 'true'
            expect(disabled).toBe(!expectedEnabled)
        })

        test.each([
            [false, false, true],
            [true, false, false],
            [false, true, false],
        ])(
            'with cloud=%s and is_debug=%s the PERSISTED_FEATURE_FLAGS banner is shown: %s',
            (cloud, isDebug, expectedVisible) => {
                setupMocks({ cloud, isDebug })

                render(<FeaturePreviews />)

                const banner = screen.queryByText(BANNER_TEXT)
                if (expectedVisible) {
                    expect(banner).toBeInTheDocument()
                } else {
                    expect(banner).not.toBeInTheDocument()
                }
            }
        )

        test.each([
            ['beta', true],
            ['alpha', true],
            ['concept', false],
        ] as const)('a %s-stage preview is listed: %s', (stage, expectedVisible) => {
            setupMocks({ features: [{ ...BETA_FEATURE, stage }] })

            render(<FeaturePreviews />)

            expect(!!screen.queryByRole('switch')).toBe(expectedVisible)
        })

        test('hides the banner when the instance has only concept previews, which this list does not render', () => {
            setupMocks({ cloud: false, features: [CONCEPT_FEATURE] })

            render(<FeaturePreviews />)

            expect(screen.queryByText(BANNER_TEXT)).not.toBeInTheDocument()
        })
    })

    describe('on the quill page', () => {
        beforeAll(() => {
            // The Base UI switch dispatches a PointerEvent on click, which jsdom lacks
            window.PointerEvent ??= window.MouseEvent as unknown as typeof PointerEvent
        })

        beforeEach(() => {
            mockedUseFeatureFlag.mockReturnValue(true)
        })

        test('turning a preview on offers to give feedback', () => {
            setupMocks()

            render(<FeaturePreviews />)
            fireEvent.click(screen.getByRole('switch'))

            expect(toast.success).toHaveBeenCalledWith(
                expect.objectContaining({
                    title: 'Customer analytics is on',
                    action: expect.objectContaining({ label: 'Give feedback' }),
                })
            )
        })

        test.each([
            ['no previews exist', FeaturePreviews, [], '', 'No feature previews right now'],
            ['no concept features exist', FeaturePreviewsComingSoon, [], '', 'Nothing coming soon right now'],
            [
                'a search matches no concept feature',
                FeaturePreviewsComingSoon,
                [],
                'zzz',
                'No matching upcoming features',
            ],
        ])('shows an empty state when %s', (_, Component, features, searchTerm, expectedTitle) => {
            setupMocks({ features, searchTerm })

            render(<Component />)

            expect(screen.getByText(expectedTitle)).toBeInTheDocument()
        })
    })
})
