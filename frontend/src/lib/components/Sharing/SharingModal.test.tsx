import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'
import { themeLogic } from 'lib/logic/themeLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { getAvailableProductFeatures, useAvailableFeatures } from '~/mocks/features'
import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightShortId, InsightModel } from '~/types'
import { AvailableFeature } from '~/types'

import { sharingLogic } from './sharingLogic'
import { getInsightDefinitionUrl, SharingModal, SharingModalProps } from './SharingModal'

const createdAt = '2022-06-28T12:30:51.459746Z'
const accessToken = '1AEQjQ2xNLGoiyI0UnNlLzOiBZWWMQ'
const dashboardId = 123
const insightShortId = 'insight456' as InsightShortId
const defaultInsightId = 456

function mockDashboardSharingConfiguration({
    enabled = true,
    passwordRequired = false,
    hasRelevantAccessControls = false,
}: {
    enabled?: boolean
    passwordRequired?: boolean
    hasRelevantAccessControls?: boolean
}): Record<string, any> {
    const sharingConfiguration = {
        created_at: createdAt,
        enabled,
        access_token: accessToken,
        password_required: passwordRequired,
        has_relevant_access_controls: hasRelevantAccessControls,
    }

    return {
        '/api/environments/:team_id/dashboards/:dashboard_id/sharing/': {
            ...sharingConfiguration,
            // Some kea-loader success payloads are wrapped.
            sharingConfiguration,
        },
    }
}

function mockInsightSharingConfiguration({
    insightId,
    passwordRequired = false,
}: {
    insightId: number
    passwordRequired?: boolean
}): Record<string, any> {
    const sharingConfiguration = {
        created_at: createdAt,
        enabled: true,
        access_token: accessToken,
        password_required: passwordRequired,
    }

    return {
        '/api/environments/:team_id/insights/:insight_id/sharing/': {
            ...sharingConfiguration,
            // Some kea-loader success payloads are wrapped.
            sharingConfiguration,
        },
        '/api/environments/:team_id/insights/': {
            results: [
                {
                    id: insightId,
                    short_id: insightShortId,
                },
            ],
        },
    }
}

describe('SharingModal (dashboard)', () => {
    // Unmount the modal portal between tests so its embed CodeSnippet (a themeLogic
    // consumer) can't commit a deferred render after a later file resets the kea store.
    afterEach(() => cleanup())

    function DashboardSharingModalWrapper({
        extraProps,
        accessControlAvailable = false,
        hasRelevantAccessControls = false,
        enabled = true,
        passwordRequired = false,
        securitySettingsAvailable = false,
        membershipLevel = OrganizationMembershipLevel.Admin,
        sharingAllowed = true,
    }: {
        extraProps?: Partial<SharingModalProps>
        accessControlAvailable?: boolean
        hasRelevantAccessControls?: boolean
        enabled?: boolean
        passwordRequired?: boolean
        securitySettingsAvailable?: boolean
        membershipLevel?: OrganizationMembershipLevel
        sharingAllowed?: boolean
    }): JSX.Element {
        // Render the dashboard sharing modal with `WHITE_LABELLING` so the UI shows
        // the branding option in the form.
        useAvailableFeatures([
            AvailableFeature.WHITE_LABELLING,
            ...(accessControlAvailable ? [AvailableFeature.ACCESS_CONTROL] : []),
            ...(securitySettingsAvailable ? [AvailableFeature.ORGANIZATION_SECURITY_SETTINGS] : []),
        ])
        initKeaTests(true, undefined, undefined, {
            ...MOCK_DEFAULT_ORGANIZATION,
            available_product_features: getAvailableProductFeatures(),
            membership_level: membershipLevel,
            allow_publicly_shared_resources: sharingAllowed,
        })
        themeLogic.mount()
        useMocks({
            get: {
                ...mockDashboardSharingConfiguration({ enabled, passwordRequired, hasRelevantAccessControls }),
                '/api/environments/:team_id/notebooks/:notebook_id/sharing/': {
                    created_at: createdAt,
                    enabled,
                    access_token: accessToken,
                    has_relevant_access_controls: hasRelevantAccessControls,
                },
            },
        })

        const props: SharingModalProps = {
            isOpen: true,
            closeModal: () => {},
            dashboardId,
            title: 'Dashboard permissions & sharing',
            ...extraProps,
        }

        return <SharingModal {...props} />
    }

    it('renders sharing options when sharing is enabled', async () => {
        render(<DashboardSharingModalWrapper />)

        expect(screen.getByText('Access control')).toBeInTheDocument()
        expect(await screen.findByText('Shared dashboard appearance')).toBeInTheDocument()

        expect(screen.getByText(/Show branding/i)).toBeInTheDocument()
        expect(screen.getByText('Public sharing')).toBeInTheDocument()
        expect(screen.getByText('Choose how the shared dashboard appears to viewers.')).toBeInTheDocument()
        expect(document.querySelector('[data-attr="sharing-theme-system"]')).toBeInTheDocument()
        expect(document.querySelector('[data-attr="sharing-theme-light"]')).toBeInTheDocument()
        expect(document.querySelector('[data-attr="sharing-theme-dark"]')).toBeInTheDocument()
        expect(screen.queryByText(/Show insight details/i)).toBeNull()
    })

    it.each([
        {
            resource: 'dashboard',
            available: true,
            configured: true,
            enabled: false,
            password: false,
            allowed: true,
            warning: true,
        },
        {
            resource: 'dashboard',
            available: true,
            configured: true,
            enabled: true,
            password: true,
            allowed: true,
            warning: true,
        },
        {
            resource: 'notebook',
            available: true,
            configured: true,
            enabled: false,
            password: false,
            allowed: true,
            warning: true,
        },
        {
            resource: 'dashboard',
            available: false,
            configured: true,
            enabled: true,
            password: false,
            allowed: true,
            warning: false,
        },
        {
            resource: 'dashboard',
            available: true,
            configured: false,
            enabled: true,
            password: false,
            allowed: true,
            warning: false,
        },
        {
            resource: 'dashboard',
            available: true,
            configured: true,
            enabled: true,
            password: false,
            allowed: false,
            warning: false,
        },
    ])(
        'warns about public $resource access with $available/$configured/$enabled/$password',
        async ({ resource, available, configured, enabled, password, allowed, warning }) => {
            render(
                <DashboardSharingModalWrapper
                    accessControlAvailable={available}
                    hasRelevantAccessControls={configured}
                    enabled={enabled}
                    passwordRequired={password}
                    sharingAllowed={allowed}
                    extraProps={
                        resource === 'notebook' ? { dashboardId: undefined, notebookShortId: 'example-notebook' } : {}
                    }
                />
            )

            await screen.findByText(`Share ${resource} publicly`)
            const banner = screen.queryByText(/Access controls do not apply to public/)
            expect(banner?.textContent).toBe(
                warning
                    ? `Anyone with the public link can view this ${resource} and its data, including people outside your organization. Access controls do not apply to public ${resource}s.`
                    : undefined
            )
            const toggle = screen.getByTestId('sharing-switch')
            expect(toggle.hasAttribute('disabled')).toBe(!allowed)
            expect(toggle).toHaveAttribute('aria-checked', String(allowed && enabled))
            expect(screen.queryByText('Public sharing is disabled for this organization.')).not.toBeInTheDocument()
        }
    )

    it.each([
        { membershipLevel: OrganizationMembershipLevel.Admin, securitySettingsAvailable: true, showsLink: true },
        { membershipLevel: OrganizationMembershipLevel.Owner, securitySettingsAvailable: true, showsLink: true },
        { membershipLevel: OrganizationMembershipLevel.Member, securitySettingsAvailable: true, showsLink: false },
        { membershipLevel: OrganizationMembershipLevel.Admin, securitySettingsAvailable: false, showsLink: false },
    ])(
        'gates the settings link for role $membershipLevel with security settings $securitySettingsAvailable',
        async ({ membershipLevel, securitySettingsAvailable, showsLink }) => {
            render(
                <DashboardSharingModalWrapper
                    accessControlAvailable
                    hasRelevantAccessControls
                    enabled={false}
                    membershipLevel={membershipLevel}
                    securitySettingsAvailable={securitySettingsAvailable}
                />
            )

            await screen.findByText('Share dashboard publicly')
            const link = screen.queryByText('Disable public sharing for your organization')
            expect(!!link).toBe(showsLink)
            expect(link?.getAttribute('href')).toEqual(
                showsLink ? expect.stringMatching(/\/settings\/organization-security$/) : undefined
            )
        }
    )

    it('updates the shared dashboard theme', async () => {
        const user = userEvent.setup()
        render(<DashboardSharingModalWrapper />)

        await user.click(await screen.findByTestId('sharing-theme-dark'))

        expect(sharingLogic({ dashboardId }).values.sharingSettings.theme).toBe('dark')
    })

    it('calls onSharingEnabledChange after the dashboard sharing switch update succeeds', async () => {
        const onSharingEnabledChange = jest.fn()

        initKeaTests()
        useMocks({
            get: mockDashboardSharingConfiguration({ enabled: false }),
            patch: mockDashboardSharingConfiguration({ enabled: true }),
        })

        const logic = sharingLogic({ dashboardId, onSharingEnabledChange })
        eventUsageLogic.mount()
        await expectLogic(logic, () => {
            logic.mount()
        }).toDispatchActions(['loadSharingConfigurationSuccess'])
        expect(onSharingEnabledChange).not.toHaveBeenCalled()

        await expectLogic(logic, () => {
            logic.actions.setIsEnabled(true)
        }).toDispatchActions(['setIsEnabledSuccess'])

        expect(onSharingEnabledChange).toHaveBeenCalledTimes(1)
        expect(onSharingEnabledChange).toHaveBeenCalledWith(true)
        logic.unmount()
        eventUsageLogic.unmount()
    })

    it('does not call onSharingEnabledChange on initial dashboard sharing load', async () => {
        const onSharingEnabledChange = jest.fn()

        initKeaTests()
        useMocks({
            get: mockDashboardSharingConfiguration({ enabled: true }),
        })

        const logic = sharingLogic({ dashboardId, onSharingEnabledChange })

        await expectLogic(logic, () => {
            logic.mount()
        }).toDispatchActions(['loadSharingConfigurationSuccess'])

        expect(onSharingEnabledChange).not.toHaveBeenCalled()
        logic.unmount()
    })
})

describe('SharingModal (insight)', () => {
    const fakeInsight: Partial<InsightModel> = {
        id: defaultInsightId,
        short_id: insightShortId,
        name: 'My insight',
    }

    afterEach(() => cleanup())

    function InsightSharingModalWrapper({ extraProps }: { extraProps?: Partial<SharingModalProps> }): JSX.Element {
        useAvailableFeatures([])
        initKeaTests()
        themeLogic.mount()
        useMocks({
            get: mockInsightSharingConfiguration({ insightId: defaultInsightId }),
        })

        const props: SharingModalProps = {
            isOpen: true,
            closeModal: () => {},
            title: 'Insight permissions & sharing',
            insightShortId: fakeInsight.short_id,
            insight: fakeInsight,
            previewIframe: true,
            ...extraProps,
        }

        return <SharingModal {...props} />
    }

    it('shows insight-specific options and no dashboard-only options', async () => {
        render(<InsightSharingModalWrapper />)

        // Insight option: Show title and description (insight-specific toggle)
        expect(await screen.findByText(/Show title and description/i)).toBeInTheDocument()
        expect(screen.getByText('Shared insight appearance')).toBeInTheDocument()
        expect(screen.getByText('Choose how the shared insight appears to viewers.')).toBeInTheDocument()

        // Dashboard-only options should not be present
        const modalTitle = await screen.findByText('Insight permissions & sharing')
        const modal = modalTitle.closest('[role="dialog"]')
        expect(modal).toBeTruthy()

        expect(within(modal as HTMLElement).queryByText(/Show insight details/i)).toBeNull()
    })
})

describe('getInsightDefinitionUrl', () => {
    it('generates a template link for an unsaved insight (raw query)', () => {
        const query = {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: null,
                        name: 'All events',
                        math: 'total',
                    },
                ],
                trendsFilter: {},
            },
        }
        const url = getInsightDefinitionUrl({ query }, 'https://app.posthog.com')
        expect(url).toMatch(/^https:\/\/app\.posthog\.com\/insights\/new#insight=TRENDS&q=%7B.*%7D(%20)?$/)
        // Should not include /project/<id>
        expect(url).not.toContain('/project/')
    })

    it('generates a template link for a saved insight (model)', () => {
        interface MinimalInsight {
            query: any
            id: number
            name: string
        }
        const savedInsight: MinimalInsight = {
            query: {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.FunnelsQuery,
                    series: [],
                    funnelsFilter: {},
                },
            },
            id: 123,
            name: 'My Funnel',
        }
        const url = getInsightDefinitionUrl(savedInsight, 'https://app.posthog.com')
        expect(url).toMatch(/^https:\/\/app\.posthog\.com\/insights\/new#insight=FUNNELS&q=%7B.*%7D(%20)?$/)
        expect(url).not.toContain('/project/')
    })
})
