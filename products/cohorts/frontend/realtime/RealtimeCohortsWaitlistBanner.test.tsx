import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { featurePreviewsLogic } from 'lib/components/FeaturePreviews/featurePreviewsLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { RealtimeCohortsWaitlistBanner } from './RealtimeCohortsWaitlistBanner'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
}))
jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: jest.fn(() => false),
}))

const mockedUseValues = useValues as jest.Mock
const mockedUseActions = useActions as jest.Mock
const mockedUseFeatureFlag = useFeatureFlag as jest.Mock

const mockLoadEarlyAccessFeatures = jest.fn()
const mockUpdateEarlyAccessFeatureEnrollment = jest.fn()

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
    }>,
    {
        isDismissed = false,
        hasRealtimeTargeting = false,
    }: { isDismissed?: boolean; hasRealtimeTargeting?: boolean } = {}
): void {
    mockedUseFeatureFlag.mockReturnValue(hasRealtimeTargeting)
    mockedUseValues.mockImplementation((logic: unknown) =>
        logic === featurePreviewsLogic
            ? { earlyAccessFeatures, waitlistSurveysEnabled: true, conceptSurveySubmissions: {} }
            : // Anything else is the banner's own dismissal logic
              { isDismissed }
    )
    mockedUseActions.mockImplementation((logic: unknown) =>
        logic === featurePreviewsLogic
            ? {
                  loadEarlyAccessFeatures: mockLoadEarlyAccessFeatures,
                  submitConceptSurvey: jest.fn(),
                  updateEarlyAccessFeatureEnrollment: mockUpdateEarlyAccessFeatureEnrollment,
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

        // Without the load, the banner only appears for someone who visited another page that fetched features.
        expect(mockLoadEarlyAccessFeatures).toHaveBeenCalled()
        expect(screen.getByText('Realtime cohorts are coming soon')).toBeInTheDocument()
        expect(screen.getByText('Beta')).toBeInTheDocument()
        expect(screen.getByPlaceholderText('email@yourcompany.com')).toBeInTheDocument()
        expect(screen.getByText('Get notified')).toBeInTheDocument()
        // The close button exists only when a dismiss key is wired.
        expect(screen.getByLabelText('close')).toBeInTheDocument()
    })

    it('offers one-click sign-up when no waitlist survey is linked', () => {
        setupMocks([{ ...CONCEPT_FEATURE, payload: {} }])

        render(<RealtimeCohortsWaitlistBanner />)

        expect(screen.queryByPlaceholderText('email@yourcompany.com')).not.toBeInTheDocument()
        fireEvent.click(screen.getByText('Get notified'))

        expect(mockUpdateEarlyAccessFeatureEnrollment).toHaveBeenCalledWith(
            FEATURE_FLAGS.REALTIME_COHORTS,
            true,
            'concept'
        )
    })

    it.each([
        ['the feature preview does not exist', []],
        ['the feature has moved past concept', [{ ...CONCEPT_FEATURE, stage: 'beta' }]],
    ])('renders nothing when %s', (_label, earlyAccessFeatures) => {
        setupMocks(earlyAccessFeatures)

        const { container } = render(<RealtimeCohortsWaitlistBanner />)

        expect(container).toBeEmptyDOMElement()
    })

    // The loader forces a network request; someone who closed the banner, or who already has
    // realtime cohorts, must not pay for it on every visit to the list.
    it.each([
        ['the banner was dismissed', { isDismissed: true }],
        ['the team already has realtime cohort targeting', { hasRealtimeTargeting: true }],
    ])('renders nothing and does not load features when %s', (_label, options) => {
        setupMocks([CONCEPT_FEATURE], options)

        const { container } = render(<RealtimeCohortsWaitlistBanner />)

        expect(container).toBeEmptyDOMElement()
        expect(mockLoadEarlyAccessFeatures).not.toHaveBeenCalled()
    })
})
