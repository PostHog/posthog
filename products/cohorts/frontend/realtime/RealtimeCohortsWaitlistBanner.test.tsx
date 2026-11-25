import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import type { ReactNode } from 'react'

import { featurePreviewsLogic } from 'lib/components/FeaturePreviews/featurePreviewsLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { cohortsSetupLogic } from '../emptyState/cohortsSetupLogic'
import { RealtimeCohortsWaitlistBanner } from './RealtimeCohortsWaitlistBanner'
import { useRealtimeCohortsServing } from './useRealtimeCohortsServing'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
}))
jest.mock('./useRealtimeCohortsServing', () => ({
    useRealtimeCohortsServing: jest.fn(() => false),
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
const mockedUseRealtimeCohortsServing = useRealtimeCohortsServing as jest.Mock
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
const BETA_FEATURE = { ...CONCEPT_FEATURE, stage: 'beta' }

function setupMocks(
    earlyAccessFeatures: Array<{
        flagKey: string
        enabled: boolean
        stage?: string
        payload?: Record<string, unknown>
    }>,
    {
        waitlistDismissed = false,
        betaDismissed = false,
        realtimeCohortsServing = false,
        setupStatus = 'has-data',
        joinedInThisBrowser = false,
        cloud = true,
    }: {
        waitlistDismissed?: boolean
        betaDismissed?: boolean
        realtimeCohortsServing?: boolean
        setupStatus?: string
        joinedInThisBrowser?: boolean
        cloud?: boolean
    } = {}
): void {
    mockedUseRealtimeCohortsServing.mockReturnValue(realtimeCohortsServing)
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
        if (logic === preflightLogic) {
            return { preflight: { cloud, is_debug: false } }
        }
        if (logic === lemonBannerLogic({ dismissKey: 'realtime-cohorts-waitlist' })) {
            return { isDismissed: waitlistDismissed }
        }
        if (logic === lemonBannerLogic({ dismissKey: 'realtime-cohorts-beta-opt-in' })) {
            return { isDismissed: betaDismissed }
        }
        throw new Error('unexpected logic')
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

    it.each([
        ['the feature is at the concept stage', {}],
        ['the feature is at the concept stage and only the beta banner was dismissed', { betaDismissed: true }],
    ])('offers the waitlist when %s', (_label, options) => {
        setupMocks([CONCEPT_FEATURE], options)

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
        ['the beta has opened', [BETA_FEATURE], {}],
        ['the beta has opened and only the waitlist was dismissed', [BETA_FEATURE], { waitlistDismissed: true }],
    ])('offers the beta opt-in for the whole project when %s', (_label, earlyAccessFeatures, options) => {
        setupMocks(earlyAccessFeatures, options)

        render(<RealtimeCohortsWaitlistBanner />)

        expect(mockLoadEarlyAccessFeatures).toHaveBeenCalled()
        expect(screen.getByText('Realtime cohorts are in beta')).toBeInTheDocument()
        expect(screen.getByText(/Joining turns on the beta for everyone in this project/)).toBeInTheDocument()
        expect(screen.getByTestId('viewed-realtime-cohorts-beta-opt-in-banner-shown')).toBeInTheDocument()

        fireEvent.click(screen.getByText('Join the beta'))

        expect(mockUpdateEarlyAccessFeatureEnrollment).toHaveBeenCalledWith(
            FEATURE_FLAGS.REALTIME_COHORTS,
            true,
            'beta'
        )
        expect(lemonToast.success).toHaveBeenCalled()
    })

    it.each([
        ['the feature preview does not exist', [], {}],
        ['the feature is at a stage with no banner', [{ ...CONCEPT_FEATURE, stage: 'alpha' }], {}],
        ['the user is already on the waitlist', [{ ...CONCEPT_FEATURE, enabled: true }], {}],
        ['the user already opted in to the beta', [{ ...BETA_FEATURE, enabled: true }], {}],
        ['the beta banner was dismissed', [BETA_FEATURE], { betaDismissed: true }],
        [
            'the waitlist was dismissed and the feature is still at concept',
            [CONCEPT_FEATURE],
            { waitlistDismissed: true },
        ],
    ])('renders nothing when %s', (_label, earlyAccessFeatures, options) => {
        setupMocks(earlyAccessFeatures, options)

        const { container } = render(<RealtimeCohortsWaitlistBanner />)

        expect(container).toBeEmptyDOMElement()
    })

    it.each([
        ['both banners were dismissed', [CONCEPT_FEATURE], { waitlistDismissed: true, betaDismissed: true }],
        ['the team already sees realtime cohorts', [CONCEPT_FEATURE], { realtimeCohortsServing: true }],
        ['the project has no cohorts yet', [CONCEPT_FEATURE], { setupStatus: 'needs-setup' }],
        ['cohort detection has not answered yet', [CONCEPT_FEATURE], { setupStatus: 'loading' }],
        ['this browser already joined the waitlist', [CONCEPT_FEATURE], { joinedInThisBrowser: true }],
        ['the instance ignores client-side flags', [BETA_FEATURE], { cloud: false }],
    ])('renders nothing and does not load features when %s', (_label, earlyAccessFeatures, options) => {
        setupMocks(earlyAccessFeatures, options)

        const { container } = render(<RealtimeCohortsWaitlistBanner />)

        expect(container).toBeEmptyDOMElement()
        expect(mockLoadEarlyAccessFeatures).not.toHaveBeenCalled()
    })
})
