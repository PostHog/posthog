import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expectLogic } from 'kea-test-utils'

import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { themeLogic } from 'lib/logic/themeLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { useAvailableFeatures } from '~/mocks/features'
import { useMocks } from '~/mocks/jest'
import type { MockResolverInfo } from '~/mocks/utils'
import { NodeKind, SharingConfigurationSettings } from '~/queries/schema/schema-general'
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
}: {
    enabled?: boolean
    passwordRequired?: boolean
}): Record<string, any> {
    const sharingConfiguration = {
        created_at: createdAt,
        enabled,
        access_token: accessToken,
        password_required: passwordRequired,
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
        licensed = true,
        organizationHasLogo = false,
    }: {
        extraProps?: Partial<SharingModalProps>
        licensed?: boolean
        organizationHasLogo?: boolean
    }): JSX.Element {
        useAvailableFeatures(licensed ? [AvailableFeature.WHITE_LABELLING] : [])
        initKeaTests(true, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT, {
            ...MOCK_DEFAULT_ORGANIZATION,
            logo_media_id: organizationHasLogo ? '0190a3c2-0000-0000-0000-000000000001' : null,
            available_product_features: licensed
                ? [{ key: AvailableFeature.WHITE_LABELLING, name: 'White labelling' }]
                : [],
        })
        themeLogic.mount()
        useMocks({
            get: mockDashboardSharingConfiguration({}),
            patch: mockDashboardSharingConfiguration({}),
        })

        const props: SharingModalProps = {
            isOpen: true,
            closeModal: () => {},
            dashboardId,
            title: 'Share dashboard',
            ...extraProps,
        }

        return <SharingModal {...props} />
    }

    it.each([true, false])('renders sharing options with white labelling available: %s', async (licensed) => {
        const user = userEvent.setup()
        render(<DashboardSharingModalWrapper licensed={licensed} />)

        expect(screen.getByText('Access control')).toBeInTheDocument()
        expect(await screen.findByText('Shared dashboard appearance')).toBeInTheDocument()

        expect(screen.getByTestId('sharing-branding-posthog')).toBeChecked()
        expect(screen.queryByTestId('sharing-show-organization-logo')).toBeNull()
        expect(screen.getByText('Show your organization logo')).toBeInTheDocument()
        if (licensed) {
            expect(screen.getByRole('link', { name: 'Add your logo' })).toHaveAttribute('target', '_blank')
            await waitFor(() => expect(screen.getByTestId('sharing-branding-posthog')).toBeEnabled())
            await user.click(screen.getByTestId('sharing-branding-posthog'))
            expect(screen.getByTestId('sharing-branding-posthog')).not.toBeChecked()
            expect(screen.queryByTestId('sharing-show-organization-logo')).toBeNull()
        } else {
            expect(screen.queryByRole('link', { name: 'Add your logo' })).toBeNull()
            expect(screen.getByTestId('sharing-branding-posthog')).toBeDisabled()
            await user.click(screen.getByRole('button', { name: 'Upgrade to Boost to show your logo' }))
            expect(upgradeModalLogic.values.upgradeModalFeatureKey).toBe(AvailableFeature.WHITE_LABELLING)
        }
        expect(screen.getByText('Public sharing')).toBeInTheDocument()
        expect(screen.getByText('Choose how the shared dashboard appears to viewers.')).toBeInTheDocument()
        expect(document.querySelector('[data-attr="sharing-theme-system"]')).toBeInTheDocument()
        expect(document.querySelector('[data-attr="sharing-theme-light"]')).toBeInTheDocument()
        expect(document.querySelector('[data-attr="sharing-theme-dark"]')).toBeInTheDocument()
        expect(screen.queryByText(/Show insight details/i)).toBeNull()
    })

    it.each([true, false])('shows the organization logo preview only when licensed: %s', async (licensed) => {
        render(<DashboardSharingModalWrapper licensed={licensed} organizationHasLogo />)

        expect(await screen.findByText('Show organization logo')).toBeInTheDocument()
        if (licensed) {
            expect(screen.getByTestId('sharing-show-organization-logo')).toBeInTheDocument()
            expect(screen.getByAltText('Your organization logo')).toBeInTheDocument()
            expect(screen.getByRole('link', { name: 'Change your logo here' })).toBeInTheDocument()
        } else {
            expect(screen.queryByTestId('sharing-show-organization-logo')).toBeNull()
            expect(screen.getByRole('button', { name: 'Upgrade to Boost to show your logo' })).toBeInTheDocument()
            expect(screen.queryByAltText('Your organization logo')).toBeNull()
            expect(screen.queryByRole('link', { name: 'Change your logo here' })).toBeNull()
        }
    })

    it('switches between PostHog branding and the organization logo in one save', async () => {
        const user = userEvent.setup()
        render(<DashboardSharingModalWrapper organizationHasLogo />)

        const savedSettings: SharingConfigurationSettings[] = []
        const saveRequest = jest.fn(async ({ request }: MockResolverInfo) => {
            const body = (await request.json()) as { settings: SharingConfigurationSettings }
            savedSettings.push(body.settings)
            return [200, { created_at: createdAt, enabled: true, access_token: accessToken, ...body }]
        })
        useMocks({
            patch: { '/api/environments/:team_id/dashboards/:dashboard_id/sharing/': saveRequest },
        })

        const posthogSwitch = await screen.findByTestId('sharing-branding-posthog')
        const organizationSwitch = screen.getByTestId('sharing-show-organization-logo')
        expect(posthogSwitch).toBeChecked()
        expect(organizationSwitch).not.toBeChecked()
        expect(organizationSwitch).toBeEnabled()

        await user.click(organizationSwitch)
        expect(sharingLogic({ dashboardId }).values.sharingSettings).toMatchObject({
            whitelabel: true,
            showOrganizationLogo: true,
        })
        await waitFor(() => expect(screen.getByTestId('sharing-branding-posthog')).not.toBeChecked())
        expect(screen.getByTestId('sharing-show-organization-logo')).toBeChecked()
        await waitFor(() => expect(saveRequest).toHaveBeenCalledTimes(1))
        expect(savedSettings[0]).toMatchObject({
            whitelabel: true,
            showOrganizationLogo: true,
        })

        await waitFor(() => expect(screen.getByTestId('sharing-branding-posthog')).toBeEnabled())
        await user.click(screen.getByTestId('sharing-branding-posthog'))
        await waitFor(() => expect(screen.getByTestId('sharing-branding-posthog')).toBeChecked())
        expect(screen.getByTestId('sharing-show-organization-logo')).not.toBeChecked()
        await waitFor(() => expect(saveRequest).toHaveBeenCalledTimes(2))
        expect(savedSettings[1]).toMatchObject({
            whitelabel: false,
            showOrganizationLogo: false,
        })
    })

    it('saves rapid changes in order so the latest settings persist', async () => {
        const user = userEvent.setup()
        render(<DashboardSharingModalWrapper organizationHasLogo />)
        let finishFirstSave!: () => void
        const firstSave = new Promise<void>((resolve) => {
            finishFirstSave = resolve
        })
        const savedSettings: SharingConfigurationSettings[] = []
        const saveRequest = jest.fn(async ({ request }: MockResolverInfo) => {
            const body = (await request.json()) as { settings: SharingConfigurationSettings }
            savedSettings.push(body.settings)
            if (savedSettings.length === 1) {
                await firstSave
            }
            return [200, { created_at: createdAt, enabled: true, access_token: accessToken, ...body }]
        })
        useMocks({ patch: { '/api/environments/:team_id/dashboards/:dashboard_id/sharing/': saveRequest } })

        await user.click(await screen.findByTestId('sharing-theme-dark'))
        await waitFor(() => expect(saveRequest).toHaveBeenCalledTimes(1))
        await user.click(screen.getByTestId('sharing-show-organization-logo'))
        expect(saveRequest).toHaveBeenCalledTimes(1)

        finishFirstSave()
        await waitFor(() => expect(saveRequest).toHaveBeenCalledTimes(2))
        expect(savedSettings[1]).toMatchObject({ theme: 'dark', whitelabel: true, showOrganizationLogo: true })
    })

    it.each([
        { setting: 'whitelabel', status: 200 },
        { setting: 'theme', status: 200 },
        { setting: 'whitelabel', status: 500 },
    ])('keeps unrelated switches idle while saving $setting ($status)', async ({ setting, status }) => {
        const user = userEvent.setup()
        render(<DashboardSharingModalWrapper />)
        await waitFor(() => expect(screen.getByTestId('sharing-branding-posthog')).toBeEnabled())
        const logic = sharingLogic({ dashboardId })
        const embedCode = logic.values.embedCode
        let finishSave!: () => void
        const pendingSave = new Promise<void>((resolve) => {
            finishSave = resolve
        })
        const saveRequest = jest.fn(async ({ request }: MockResolverInfo) => {
            const body = (await request.json()) as { settings: SharingConfigurationSettings }
            await pendingSave
            return [status, { created_at: createdAt, enabled: true, access_token: accessToken, ...body }]
        })
        useMocks({
            patch: { '/api/environments/:team_id/dashboards/:dashboard_id/sharing/': saveRequest },
        })

        const control = setting === 'whitelabel' ? 'sharing-branding-posthog' : 'sharing-theme-dark'
        await user.click(screen.getByTestId(control))
        await waitFor(() => expect(saveRequest).toHaveBeenCalledTimes(1))

        expect(screen.getByTestId('sharing-switch')).toBeEnabled()
        if (setting === 'whitelabel') {
            expect(screen.getByTestId('sharing-branding-posthog')).toBeDisabled()
        } else {
            expect(screen.getByTestId('sharing-branding-posthog')).toBeEnabled()
        }

        finishSave()
        await waitFor(() => expect(screen.getByTestId('sharing-branding-posthog')).toBeEnabled())
        await waitFor(() => expect(logic.values.sharingConfigurationLoading).toBe(false))
        expect(logic.values.embedCode).toBe(embedCode)
        expect(logic.values.embedCode).not.toMatch(/\skey=/)
        if (status === 500) {
            await waitFor(() => expect(logic.values.sharingSettings.whitelabel).toBe(false))
        }
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
