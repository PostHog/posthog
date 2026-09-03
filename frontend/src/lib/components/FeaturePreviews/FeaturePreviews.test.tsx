import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useActions, useAsyncActions, useValues } from 'kea'

import { preflightLogic } from 'lib/logic/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { FeaturePreviews } from './FeaturePreviews'
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

jest.mock('lib/components/Cards/BasicCard', () => ({
    BasicCard: ({ children }: { children: React.ReactNode }) => <div data-attr="basic-card">{children}</div>,
}))

const mockedUseValues = useValues as jest.Mock
const mockedUseActions = useActions as jest.Mock
const mockedUseAsyncActions = useAsyncActions as jest.Mock

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
}: { cloud?: boolean; isDebug?: boolean; features?: EnrichedEarlyAccessFeature[] } = {}): void {
    mockedUseValues.mockImplementation((logic: unknown) => {
        if (logic === featurePreviewsLogic) {
            return {
                filteredEarlyAccessFeatures: features,
                rawEarlyAccessFeaturesLoading: false,
                searchTerm: '',
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

    test.each([
        [false, false, false],
        [true, false, true],
        [false, true, true],
    ])('with cloud=%s and is_debug=%s the toggle switch is enabled: %s', (cloud, isDebug, expectedEnabled) => {
        setupMocks({ cloud, isDebug })

        render(<FeaturePreviews />)

        const toggle = screen.getByRole('switch')
        if (expectedEnabled) {
            expect(toggle).toBeEnabled()
        } else {
            expect(toggle).toBeDisabled()
        }
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

    test('hides the banner when the instance has only concept previews, which this list does not render', () => {
        setupMocks({ cloud: false, features: [CONCEPT_FEATURE] })

        render(<FeaturePreviews />)

        expect(screen.queryByText(BANNER_TEXT)).not.toBeInTheDocument()
    })
})
