import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import type { ReactNode } from 'react'

import { featurePreviewsLogic } from 'lib/components/FeaturePreviews/featurePreviewsLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { cohortsSetupLogic } from '../emptyState/cohortsSetupLogic'
import { RealtimeCohortsWaitlistBanner } from './RealtimeCohortsWaitlistBanner'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
}))
jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: jest.fn(() => false),
}))
jest.mock('posthog-js', () => ({ __esModule: true, default: { get_property: jest.fn() } }))
jest.mock('@posthog/react', () => ({
    PostHogCaptureOnViewed: ({ name, children }: { name: string; children: ReactNode }) => (
        <div data-attr={`viewed-${name}`}>{children}</div>
    ),
}))
jest.mock('lib/lemon-ui/LemonToast', () => ({ lemonToast: { success: jest.fn() } }))

const mockedUseValues = useValues as jest.Mock
const mockedUseActions = useActions as jest.Mock
const mockedUseFeatureFlag = useFeatureFlag as jest.Mock
const mockedGetProperty = posthog.get_property as jest.Mock

const mockLoadEarlyAccessFeatures = jest.fn()
const mockUpdateEarlyAccessFeatureEnrollment = jest.fn()
const mockSubmitConceptSurvey = jest.fn()

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
        setupStatus = 'has-data',
        joinedInThisBrowser = false,
    }: {
        isDismissed?: boolean
        hasRealtimeTargeting?: boolean
        setupStatus?: string
        joinedInThisBrowser?: boolean
    } = {}
): void {
    mockedUseFeatureFlag.mockReturnValue(hasRealtimeTargeting)
    mockedGetProperty.mockReturnValue(
        joinedInThisBrowser ? { [`$feature_enrollment/${FEATURE_FLAGS.REALTIME_COHORTS}`]: true } : {}
    )
    mockedUseValues.mockImplementation((logic: unknown) => {
        if (logic === featurePreviewsLogic) {
            return { earlyAccessFeatures, waitlistSurveysEnabled: true, conceptSurveySubmissions: {} }
        }
        if (logic === cohortsSetupLogic) {
            return { setupStatus }
        }
        return { isDismissed }
    })
    mockedUseActions.mockImplementation((logic: unknown) =>
        logic === featurePreviewsLogic
            ? {
                  loadEarlyAccessFeatures: mockLoadEarlyAccessFeatures,
                  submitConceptSurvey: mockSubmitConceptSurvey,
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
        expect(screen.getByText('Get notified')).toBeInTheDocument()
        expect(screen.getByLabelText('close')).toBeInTheDocument()
        expect(screen.getByTestId('viewed-realtime-cohorts-waitlist-banner-shown')).toBeInTheDocument()
    })

    // The account already identifies the user, so the banner never asks for an email, even when the
    // feature links a waitlist survey and the surveys flag is on.
    it('collects interest with one click and no email field', () => {
        setupMocks([CONCEPT_FEATURE])

        render(<RealtimeCohortsWaitlistBanner />)

        expect(screen.queryByPlaceholderText('email@yourcompany.com')).not.toBeInTheDocument()
        fireEvent.click(screen.getByText('Get notified'))

        expect(mockUpdateEarlyAccessFeatureEnrollment).toHaveBeenCalledWith(
            FEATURE_FLAGS.REALTIME_COHORTS,
            true,
            'concept'
        )
        expect(mockSubmitConceptSurvey).not.toHaveBeenCalled()
        expect(lemonToast.success).toHaveBeenCalled()
    })

    it.each([
        ['the feature preview does not exist', []],
        ['the feature has moved past concept', [{ ...CONCEPT_FEATURE, stage: 'beta' }]],
        ['the user is already on the waitlist', [{ ...CONCEPT_FEATURE, enabled: true }]],
    ])('renders nothing when %s', (_label, earlyAccessFeatures) => {
        setupMocks(earlyAccessFeatures)

        const { container } = render(<RealtimeCohortsWaitlistBanner />)

        expect(container).toBeEmptyDOMElement()
    })

    it.each([
        ['the banner was dismissed', { isDismissed: true }],
        ['the team already has realtime cohort targeting', { hasRealtimeTargeting: true }],
        ['the project has no cohorts yet', { setupStatus: 'needs-setup' }],
        ['cohort detection has not answered yet', { setupStatus: 'loading' }],
        ['this browser already joined the waitlist', { joinedInThisBrowser: true }],
    ])('renders nothing and does not load features when %s', (_label, options) => {
        setupMocks([CONCEPT_FEATURE], options)

        const { container } = render(<RealtimeCohortsWaitlistBanner />)

        expect(container).toBeEmptyDOMElement()
        expect(mockLoadEarlyAccessFeatures).not.toHaveBeenCalled()
    })
})
