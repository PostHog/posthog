import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useActions, useMountedLogic, useValues } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { FeaturePreviewGateConfig } from '~/types'

import { featurePreviewsLogic } from '../../FeaturePreviews/featurePreviewsLogic'
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
const mockUpdateEarlyAccessFeatureEnrollment = jest.fn()

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

function setupMocks({
    earlyAccessFeatures = [],
    activeSceneId = null,
    featureFlags = {},
}: {
    earlyAccessFeatures?: Array<{ flagKey: string; enabled: boolean; stage?: string }>
    activeSceneId?: string | null
    featureFlags?: Record<string, boolean | string>
} = {}): void {
    mockedUseMountedLogic.mockReturnValue({})

    mockedUseValues.mockImplementation((logic: unknown) => {
        if (isFeaturePreviewsLogicRef(logic)) {
            return { earlyAccessFeatures }
        }
        if (isSceneLogicRef(logic)) {
            return { activeSceneId }
        }
        if (isFeatureFlagLogicRef(logic)) {
            return { featureFlags }
        }
        return {}
    })

    mockedUseActions.mockImplementation((logic: unknown) => {
        if (isFeaturePreviewsLogicRef(logic)) {
            return {
                loadEarlyAccessFeatures: mockLoadEarlyAccessFeatures,
                updateEarlyAccessFeatureEnrollment: mockUpdateEarlyAccessFeatureEnrollment,
            }
        }
        return {}
    })
}

describe('FeaturePreviewSceneGate', () => {
    beforeEach(() => {
        jest.clearAllMocks()
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

        test('does not show toggle for a different feature flag key', () => {
            setupMocks({
                earlyAccessFeatures: [{ flagKey: 'some-other-flag', enabled: true }],
            })

            render(<FeaturePreviewSceneGate config={BASE_CONFIG}>{CHILDREN}</FeaturePreviewSceneGate>)

            expect(screen.getByText('Open feature previews')).toBeInTheDocument()
            expect(screen.queryByRole('switch')).not.toBeInTheDocument()
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
