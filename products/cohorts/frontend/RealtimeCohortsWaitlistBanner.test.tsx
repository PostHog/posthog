import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { featurePreviewsLogic } from 'lib/components/FeaturePreviews/featurePreviewsLogic'
import { FEATURE_FLAGS } from 'lib/constants'

import { RealtimeCohortsWaitlistBanner } from './RealtimeCohortsWaitlistBanner'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
}))

const mockedUseValues = useValues as jest.Mock
const mockedUseActions = useActions as jest.Mock

const CONCEPT_FEATURE = {
    flagKey: FEATURE_FLAGS.REALTIME_COHORTS,
    name: 'Realtime cohorts',
    enabled: false,
    stage: 'concept',
    payload: { survey_id: 'survey-1' },
}

function setupMocks(
    earlyAccessFeatures: Array<{
        flagKey: string
        enabled: boolean
        stage?: string
        payload?: Record<string, unknown>
    }>
): void {
    mockedUseValues.mockImplementation((logic: unknown) =>
        logic === featurePreviewsLogic
            ? { earlyAccessFeatures, waitlistSurveysEnabled: true, conceptSurveySubmissions: {} }
            : // Anything else is the banner's own dismissal logic, which must report "not dismissed"
              { isDismissed: false }
    )
    mockedUseActions.mockImplementation((logic: unknown) =>
        logic === featurePreviewsLogic
            ? {
                  loadEarlyAccessFeatures: jest.fn(),
                  submitConceptSurvey: jest.fn(),
                  updateEarlyAccessFeatureEnrollment: jest.fn(),
              }
            : { dismiss: jest.fn() }
    )
}

describe('RealtimeCohortsWaitlistBanner', () => {
    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
    })

    it('offers the waitlist while the feature is at the concept stage', () => {
        setupMocks([CONCEPT_FEATURE])

        render(<RealtimeCohortsWaitlistBanner />)

        expect(screen.getByText('Realtime cohorts are coming soon')).toBeInTheDocument()
        expect(screen.getByText('Beta')).toBeInTheDocument()
        expect(screen.getByPlaceholderText('email@yourcompany.com')).toBeInTheDocument()
        expect(screen.getByText('Get notified')).toBeInTheDocument()
    })

    it.each([
        ['the feature preview does not exist', []],
        ['the feature has moved past concept', [{ ...CONCEPT_FEATURE, stage: 'beta' }]],
    ])('renders nothing when %s', (_label, earlyAccessFeatures) => {
        setupMocks(earlyAccessFeatures)

        const { container } = render(<RealtimeCohortsWaitlistBanner />)

        expect(container).toBeEmptyDOMElement()
    })
})
