import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useActions, useMountedLogic, useValues } from 'kea'

import { featurePreviewsLogic } from 'lib/components/FeaturePreviews/featurePreviewsLogic'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { FeaturePreviewGateConfig } from '~/types'

import { FeaturePreviewSceneGate } from './FeaturePreviewSceneGate'

jest.mock('posthog-js')

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
    useMountedLogic: jest.fn(),
}))

jest.mock('scenes/sceneLogic', () => ({
    sceneLogic: { __mock: 'sceneLogic' },
}))

jest.mock('scenes/scenes', () => ({
    sceneConfigurations: {
        CustomerAnalytics: { name: 'Customer analytics', description: 'Analytics for customers', iconType: 'default' },
        Error404: { name: 'Not found', iconType: 'default' },
        Metrics: { name: 'Metrics', description: 'Application metrics', iconType: 'default' },
    },
}))

jest.mock('lib/components/ProductIntroduction/ProductIntroduction', () => ({
    ProductIntroduction: ({
        titleOverride,
        description,
        actionElementOverride,
    }: {
        titleOverride: string
        description: string
        actionElementOverride: React.ReactNode
    }) => (
        <div data-attr="product-introduction">
            <div data-attr="product-title">{titleOverride}</div>
            <div data-attr="product-description">{description}</div>
            {actionElementOverride}
        </div>
    ),
}))

jest.mock('./SceneContent', () => ({
    SceneContent: ({ children }: { children: React.ReactNode }) => <div data-attr="scene-content">{children}</div>,
}))

jest.mock('./SceneTitleSection', () => ({
    SceneTitleSection: ({ name }: { name: string }) => <div data-attr="scene-title-section">{name}</div>,
}))

const mockedUseValues = useValues as jest.Mock
const mockedUseActions = useActions as jest.Mock
const mockedUseMountedLogic = useMountedLogic as jest.Mock

const mockLoadEarlyAccessFeatures = jest.fn()
// Mirrors posthog-js: enrollment takes effect locally the moment it is stored, so the
// enriched feature flips to enabled and the scene gate re-renders on the same render pass.
const mockUpdateEarlyAccessFeatureEnrollment = jest.fn((flagKey: string, enabled: boolean) => {
    enrolledFlags = enabled ? [...enrolledFlags, flagKey] : enrolledFlags.filter((key) => key !== flagKey)
})
let enrolledFlags: string[] = []
const mockSubmitConceptSurvey = jest.fn()
const mockAddProductIntentForCrossSell = jest.fn()
const mockOpenSupportForm = jest.fn()

const BASE_CONFIG: FeaturePreviewGateConfig = {
    flag: 'customer-analytics-roadmap',
    title: 'Try Customer analytics',
    description: 'Get context about your customers.',
    docsURL: 'https://posthog.com/docs/customer-analytics',
}

const CHILDREN = <div data-attr="scene-content-rendered">scene content</div>

function isFeaturePreviewsLogicRef(logic: unknown): boolean {
    return logic === featurePreviewsLogic
}

function isSceneLogicRef(logic: unknown): boolean {
    return (logic as { __mock?: string } | null | undefined)?.__mock === 'sceneLogic'
}

function isFeatureFlagLogicRef(logic: unknown): boolean {
    return logic === featureFlagLogic
}

function isPreflightLogicRef(logic: unknown): boolean {
    return logic === preflightLogic
}

function isSupportLogicRef(logic: unknown): boolean {
    return logic === supportLogic
}

// productSetupStatusLogic is keyed, so the gate calls it as a factory; the mock returns a
// stable sentinel and we identity-compare against what the factory hands the component.
function isProductSetupStatusLogicRef(logic: unknown): boolean {
    return (logic as { __mock?: string } | null | undefined)?.__mock === 'productSetupStatusLogic'
}

jest.mock('lib/components/ProductEmptyState/productSetupStatusLogic', () => {
    const sentinel = { __mock: 'productSetupStatusLogic' }
    return { productSetupStatusLogic: () => sentinel }
})

// The gate's settling state lives in a kea logic (repo rule: no business logic in hooks).
// Mock the module so tests steer it through this sentinel: the factory returns an object whose
// identity marks it, and `mockSettling`/`mockStartSettling` stand in for its value and action.
jest.mock('./featurePreviewGateSettlingLogic', () => ({
    featurePreviewGateSettlingLogic: () => ({ __mock: 'featurePreviewGateSettlingLogic' }),
}))

let mockSettling = false
const mockStartSettling = jest.fn(() => {
    mockSettling = true
})
const mockMarkServerCaughtUp = jest.fn()

function isSettlingLogicRef(logic: unknown): boolean {
    return (logic as { __mock?: string } | null | undefined)?.__mock === 'featurePreviewGateSettlingLogic'
}

function setupMocks({
    earlyAccessFeatures = [],
    waitlistSurveysEnabled = false,
    conceptSurveySubmissions = {},
    activeSceneId = null,
    featureFlags = {},
    cloud = true,
    isDebug = false,
    setupStatus = 'unknown',
}: {
    earlyAccessFeatures?: Array<{
        flagKey: string
        enabled: boolean
        stage?: string
        payload?: Record<string, unknown>
    }>
    waitlistSurveysEnabled?: boolean
    conceptSurveySubmissions?: Record<string, boolean>
    activeSceneId?: string | null
    featureFlags?: Record<string, boolean | string>
    cloud?: boolean
    isDebug?: boolean
    setupStatus?: string
} = {}): void {
    mockedUseMountedLogic.mockReturnValue({})

    mockedUseValues.mockImplementation((logic: unknown) => {
        if (isFeaturePreviewsLogicRef(logic)) {
            return {
                earlyAccessFeatures: earlyAccessFeatures.map((feature) =>
                    enrolledFlags.includes(feature.flagKey) ? { ...feature, enabled: true } : feature
                ),
                waitlistSurveysEnabled,
                conceptSurveySubmissions,
            }
        }
        if (isSceneLogicRef(logic)) {
            return { activeSceneId }
        }
        if (isFeatureFlagLogicRef(logic)) {
            return { featureFlags }
        }
        if (isPreflightLogicRef(logic)) {
            return { preflight: { cloud, is_debug: isDebug } }
        }
        if (isProductSetupStatusLogicRef(logic)) {
            return { status: setupStatus }
        }
        if (isSettlingLogicRef(logic)) {
            return { settling: mockSettling }
        }
        return {}
    })

    mockedUseActions.mockImplementation((logic: unknown) => {
        if (isFeaturePreviewsLogicRef(logic)) {
            return {
                loadEarlyAccessFeatures: mockLoadEarlyAccessFeatures,
                updateEarlyAccessFeatureEnrollment: mockUpdateEarlyAccessFeatureEnrollment,
                submitConceptSurvey: mockSubmitConceptSurvey,
                addProductIntentForCrossSell: mockAddProductIntentForCrossSell,
            }
        }
        if (isSupportLogicRef(logic)) {
            return { openSupportForm: mockOpenSupportForm }
        }
        if (isSettlingLogicRef(logic)) {
            return { startSettling: mockStartSettling, markServerCaughtUp: mockMarkServerCaughtUp }
        }
        return {}
    })
}

describe('FeaturePreviewSceneGate', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        enrolledFlags = []
        mockSettling = false
        setupMocks()
    })

    afterEach(() => {
        cleanup()
    })

    describe('wrapper behavior', () => {
        test('renders children when flag is on', () => {
            setupMocks({ featureFlags: { [BASE_CONFIG.flag]: true } })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            expect(screen.getByTestId('scene-content-rendered')).toBeInTheDocument()
            expect(screen.queryByTestId('product-introduction')).not.toBeInTheDocument()
        })

        test('opting in starts the settling window', () => {
            setupMocks({ earlyAccessFeatures: [{ flagKey: BASE_CONFIG.flag, enabled: false, stage: 'alpha' }] })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)
            fireEvent.click(screen.getByRole('switch'))

            expect(mockStartSettling).toHaveBeenCalledTimes(1)
        })

        test('while settling with the flag on, holds on an enabling state instead of mounting a scene whose API still 403s', () => {
            // The browser evaluates the flag on the moment enrollment is stored locally, while the
            // API keeps denying until the enrollment person property is ingested. Mounting the
            // scene in that window is what showed "Detect status failed" until a reload.
            mockSettling = true
            setupMocks({ featureFlags: { [BASE_CONFIG.flag]: true } })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            expect(screen.getByTestId('feature-preview-enabling')).toBeInTheDocument()
            expect(screen.getByText(/turning the feature preview on/i)).toBeInTheDocument()
            expect(screen.queryByTestId('scene-content-rendered')).not.toBeInTheDocument()
            expect(screen.queryByTestId('product-introduction')).not.toBeInTheDocument()
        })

        test('a rejected enrollment (impersonated session) never starts settling', () => {
            // featurePreviewsLogic refuses enrollment for impersonated sessions, so the flag never
            // flips and there is nothing to wait on - the gate must stay exactly as it was.
            ;(window as unknown as { IMPERSONATED_SESSION?: boolean }).IMPERSONATED_SESSION = true
            setupMocks({ earlyAccessFeatures: [{ flagKey: BASE_CONFIG.flag, enabled: false, stage: 'alpha' }] })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)
            fireEvent.click(screen.getByRole('switch'))

            expect(mockStartSettling).not.toHaveBeenCalled()
            expect(screen.queryByTestId('feature-preview-enabling')).not.toBeInTheDocument()
            expect(screen.getByTestId('product-introduction')).toBeInTheDocument()
            delete (window as unknown as { IMPERSONATED_SESSION?: boolean }).IMPERSONATED_SESSION
        })

        test('a successful server detection ends the enabling state early', () => {
            // The window exists because the API lags the browser. Once the product's own setup
            // detection gets a real answer from the server, the wait has done its job.
            mockSettling = true
            setupMocks({ featureFlags: { [BASE_CONFIG.flag]: true }, setupStatus: 'has-data' })

            render(
                <FeaturePreviewSceneGate config={{ ...BASE_CONFIG, productIntent: ProductKey.METRICS }}>
                    {CHILDREN}
                </FeaturePreviewSceneGate>
            )

            expect(mockMarkServerCaughtUp).toHaveBeenCalled()
        })

        test('no detection answer yet keeps the wait running', () => {
            mockSettling = true
            setupMocks({ featureFlags: { [BASE_CONFIG.flag]: true }, setupStatus: 'loading' })

            render(
                <FeaturePreviewSceneGate config={{ ...BASE_CONFIG, productIntent: ProductKey.METRICS }}>
                    {CHILDREN}
                </FeaturePreviewSceneGate>
            )

            expect(mockMarkServerCaughtUp).not.toHaveBeenCalled()
            expect(screen.getByTestId('feature-preview-enabling')).toBeInTheDocument()
        })

        test('renders the gate when flag is off', () => {
            setupMocks({ featureFlags: { [BASE_CONFIG.flag]: false } })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            expect(screen.getByTestId('product-introduction')).toBeInTheDocument()
            expect(screen.queryByTestId('scene-content-rendered')).not.toBeInTheDocument()
        })

        test('renders the gate when the flag is missing from featureFlags', () => {
            setupMocks({ featureFlags: {} })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            expect(screen.getByTestId('product-introduction')).toBeInTheDocument()
            expect(screen.queryByTestId('scene-content-rendered')).not.toBeInTheDocument()
        })
    })

    describe('gate UI rendering', () => {
        test('shows "Open feature previews" button when feature is not in early access list', () => {
            setupMocks({ earlyAccessFeatures: [] })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            expect(screen.getByText('Open feature previews')).toBeInTheDocument()
            expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
        })

        test('shows toggle switch when feature is found in early access list', () => {
            setupMocks({
                earlyAccessFeatures: [{ flagKey: BASE_CONFIG.flag, enabled: false }],
            })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            expect(screen.queryByText('Open feature previews')).not.toBeInTheDocument()
            expect(screen.getByText('Enable feature preview')).toBeInTheDocument()
            expect(screen.getByRole('switch')).toBeInTheDocument()
        })

        test('reflects enabled state on the toggle switch', () => {
            setupMocks({
                earlyAccessFeatures: [{ flagKey: BASE_CONFIG.flag, enabled: true }],
            })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            // LemonSwitch uses CSS class to indicate checked state, not aria-checked
            const switchWrapper = document.querySelector('.LemonSwitch')
            expect(switchWrapper).toHaveClass('LemonSwitch--checked')
        })

        test('reflects disabled state on the toggle switch', () => {
            setupMocks({
                earlyAccessFeatures: [{ flagKey: BASE_CONFIG.flag, enabled: false }],
            })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            const switchWrapper = document.querySelector('.LemonSwitch')
            expect(switchWrapper).not.toHaveClass('LemonSwitch--checked')
        })

        test('shows config title in the product introduction', () => {
            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            expect(screen.getByTestId('product-title')).toHaveTextContent(BASE_CONFIG.title)
        })

        test('shows config description in the product introduction', () => {
            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            expect(screen.getByTestId('product-description')).toHaveTextContent(BASE_CONFIG.description)
        })

        test('does not render scene title section when there is no active scene', () => {
            setupMocks({ activeSceneId: null })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            expect(screen.queryByTestId('scene-title-section')).not.toBeInTheDocument()
        })

        test('renders scene title section when active scene has a name in sceneConfigurations', () => {
            setupMocks({ activeSceneId: 'CustomerAnalytics' })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            expect(screen.getByTestId('scene-title-section')).toHaveTextContent('Customer analytics')
        })

        test('config sceneId overrides the active scene for the title, so a flag-hidden route is not titled "Not found"', () => {
            setupMocks({ activeSceneId: 'Error404' })

            render(
                <FeaturePreviewSceneGate config={{ ...BASE_CONFIG, sceneId: 'Metrics' }}>
                    {CHILDREN}
                </FeaturePreviewSceneGate>
            )

            expect(screen.getByTestId('scene-title-section')).toHaveTextContent('Metrics')
            expect(screen.queryByText('Not found')).not.toBeInTheDocument()
        })

        test('does not show toggle for a different feature flag key', () => {
            setupMocks({
                earlyAccessFeatures: [{ flagKey: 'some-other-flag', enabled: true }],
            })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            expect(screen.getByText('Open feature previews')).toBeInTheDocument()
            expect(screen.queryByRole('switch')).not.toBeInTheDocument()
        })

        test.each([
            [false, false, false],
            [true, false, true],
            [false, true, true],
        ])('with cloud=%s and is_debug=%s the toggle switch is enabled: %s', (cloud, isDebug, expectedEnabled) => {
            setupMocks({
                earlyAccessFeatures: [{ flagKey: BASE_CONFIG.flag, enabled: false }],
                cloud,
                isDebug,
            })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

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
            'with cloud=%s and is_debug=%s the PERSISTED_FEATURE_FLAGS note is shown: %s',
            (cloud, isDebug, expectedVisible) => {
                setupMocks({ earlyAccessFeatures: [], cloud, isDebug })

                render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

                const note = screen.queryByText(/controlled by the PERSISTED_FEATURE_FLAGS environment variable/)
                if (expectedVisible) {
                    expect(note).toBeInTheDocument()
                } else {
                    expect(note).not.toBeInTheDocument()
                }
            }
        )
    })

    describe('concept stage (waitlist)', () => {
        const CONCEPT_FEATURE = {
            flagKey: BASE_CONFIG.flag,
            enabled: false,
            stage: 'concept',
            payload: { survey_id: 'survey-1' },
        }

        test('shows an email waitlist form instead of the dead toggle for a concept feature', () => {
            setupMocks({ earlyAccessFeatures: [CONCEPT_FEATURE], waitlistSurveysEnabled: true })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            expect(screen.getByPlaceholderText('email@yourcompany.com')).toBeInTheDocument()
            expect(screen.getByText('Get notified')).toBeInTheDocument()
            expect(screen.queryByRole('switch')).not.toBeInTheDocument()
        })

        test('shows the confirmation once the user is on the waitlist', () => {
            setupMocks({
                earlyAccessFeatures: [CONCEPT_FEATURE],
                waitlistSurveysEnabled: true,
                conceptSurveySubmissions: { [BASE_CONFIG.flag]: true },
            })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            expect(screen.getByText(/Thanks — we'll email you when it's ready/)).toBeInTheDocument()
            expect(screen.queryByRole('switch')).not.toBeInTheDocument()
        })

        test('submits the waitlist survey and registers product intent', async () => {
            setupMocks({ earlyAccessFeatures: [CONCEPT_FEATURE], waitlistSurveysEnabled: true })

            render(
                <FeaturePreviewSceneGate config={{ ...BASE_CONFIG, productIntent: 'metrics' as ProductKey }}>
                    {CHILDREN}
                </FeaturePreviewSceneGate>
            )
            await userEvent.type(screen.getByPlaceholderText('email@yourcompany.com'), 'user@example.com')
            await userEvent.click(screen.getByText('Get notified'))

            expect(mockSubmitConceptSurvey).toHaveBeenCalledWith(BASE_CONFIG.flag, 'user@example.com')
            expect(mockAddProductIntentForCrossSell).toHaveBeenCalledWith(
                expect.objectContaining({
                    to: 'metrics',
                    intent_context: 'feature_preview_enabled',
                })
            )
        })

        test('does not register product intent for an impersonated session', async () => {
            setupMocks({ earlyAccessFeatures: [CONCEPT_FEATURE], waitlistSurveysEnabled: true })
            window.IMPERSONATED_SESSION = true

            try {
                render(
                    <FeaturePreviewSceneGate config={{ ...BASE_CONFIG, productIntent: 'metrics' as ProductKey }}>
                        {CHILDREN}
                    </FeaturePreviewSceneGate>
                )
                await userEvent.type(screen.getByPlaceholderText('email@yourcompany.com'), 'user@example.com')
                await userEvent.click(screen.getByText('Get notified'))

                // The survey submit is attempted (the logic shows the rejection toast), but the
                // adoption signal must not fire for a signup the backend will refuse.
                expect(mockAddProductIntentForCrossSell).not.toHaveBeenCalled()
            } finally {
                delete window.IMPERSONATED_SESSION
            }
        })

        test('falls back to the toggle for a concept feature without a waitlist survey', () => {
            setupMocks({
                earlyAccessFeatures: [{ flagKey: BASE_CONFIG.flag, enabled: false, stage: 'concept' }],
                waitlistSurveysEnabled: false,
            })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            expect(screen.getByRole('switch')).toBeInTheDocument()
        })
    })

    describe('alpha stage (self-serve enrollment)', () => {
        const ALPHA_FEATURE = {
            flagKey: BASE_CONFIG.flag,
            enabled: false,
            stage: 'alpha',
            payload: { survey_id: 'survey-1' },
        }

        test('shows the enrollment toggle even when the feature carries a waitlist survey', () => {
            setupMocks({ earlyAccessFeatures: [ALPHA_FEATURE], waitlistSurveysEnabled: true })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            expect(screen.getByRole('switch')).toBeInTheDocument()
            expect(screen.queryByPlaceholderText('email@yourcompany.com')).not.toBeInTheDocument()
        })

        test('toggling on enrolls with the alpha stage, which unlocks the flag', async () => {
            setupMocks({ earlyAccessFeatures: [ALPHA_FEATURE] })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)
            await userEvent.click(screen.getByRole('switch'))

            expect(mockUpdateEarlyAccessFeatureEnrollment).toHaveBeenCalledWith(BASE_CONFIG.flag, true, 'alpha')
        })
    })

    describe('request access', () => {
        const CONFIG_WITH_SUPPORT: FeaturePreviewGateConfig = {
            ...BASE_CONFIG,
            offerRequestAccess: true,
        }

        test('does not show "Request access" when config does not offer it', () => {
            setupMocks({ earlyAccessFeatures: [] })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            expect(screen.queryByText('Request access')).not.toBeInTheDocument()
        })

        test('does not show "Request access" on a self-hosted instance', () => {
            setupMocks({ earlyAccessFeatures: [], cloud: false })

            render(<FeaturePreviewSceneGate config={CONFIG_WITH_SUPPORT}>{CHILDREN}</FeaturePreviewSceneGate>)

            expect(screen.queryByText('Request access')).not.toBeInTheDocument()
        })

        test('opens the support form targeting the configured area when "Request access" is clicked', async () => {
            setupMocks({ earlyAccessFeatures: [], cloud: true })

            render(<FeaturePreviewSceneGate config={CONFIG_WITH_SUPPORT}>{CHILDREN}</FeaturePreviewSceneGate>)
            await userEvent.click(screen.getByText('Request access'))

            expect(mockOpenSupportForm).toHaveBeenCalledWith(expect.objectContaining({ kind: 'support' }))
        })
    })

    describe('behavior on mount', () => {
        test('calls loadEarlyAccessFeatures on mount when gated', () => {
            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            expect(mockLoadEarlyAccessFeatures).toHaveBeenCalledTimes(1)
        })

        test('does not call loadEarlyAccessFeatures when the flag is on', () => {
            setupMocks({ featureFlags: { [BASE_CONFIG.flag]: true } })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            expect(mockLoadEarlyAccessFeatures).not.toHaveBeenCalled()
        })
    })

    describe('toggle interaction', () => {
        test('calls updateEarlyAccessFeatureEnrollment with flag key, true, and stage when toggled on', async () => {
            const feature = { flagKey: BASE_CONFIG.flag, enabled: false, stage: 'beta' }
            setupMocks({ earlyAccessFeatures: [feature] })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)
            await userEvent.click(screen.getByRole('switch'))

            expect(mockUpdateEarlyAccessFeatureEnrollment).toHaveBeenCalledWith(BASE_CONFIG.flag, true, feature.stage)
        })

        test('calls updateEarlyAccessFeatureEnrollment with flag key, false, and stage when toggled off', async () => {
            const feature = { flagKey: BASE_CONFIG.flag, enabled: true, stage: 'beta' }
            setupMocks({ earlyAccessFeatures: [feature] })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)
            await userEvent.click(screen.getByRole('switch'))

            expect(mockUpdateEarlyAccessFeatureEnrollment).toHaveBeenCalledWith(BASE_CONFIG.flag, false, feature.stage)
        })
    })
})
