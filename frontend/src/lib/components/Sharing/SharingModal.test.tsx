import '@testing-library/jest-dom'

import { render, screen, within } from '@testing-library/react'

import { useAvailableFeatures } from '~/mocks/features'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { InsightShortId, QueryBasedInsightModel } from '~/types'
import { AvailableFeature } from '~/types'

import { SharingModal, SharingModalProps } from './SharingModal'

const createdAt = '2022-06-28T12:30:51.459746Z'
const accessToken = '1AEQjQ2xNLGoiyI0UnNlLzOiBZWWMQ'
const dashboardId = 123
const insightShortId = 'insight456' as InsightShortId
const defaultInsightId = 456

function mockDashboardSharingConfiguration({
    passwordRequired = false,
}: {
    passwordRequired?: boolean
}): Record<string, any> {
    const sharingConfiguration = {
        created_at: createdAt,
        enabled: true,
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
    function DashboardSharingModalWrapper({ extraProps }: { extraProps?: Partial<SharingModalProps> }): JSX.Element {
        // Render the dashboard sharing modal with `WHITE_LABELLING` so the UI shows
        // the branding option in the form.
        useAvailableFeatures([AvailableFeature.WHITE_LABELLING])
        initKeaTests()
        useMocks({
            get: mockDashboardSharingConfiguration({}),
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

        // Sharing section label
        expect(await screen.findByText('Sharing')).toBeInTheDocument()

        // Access control section
        expect(screen.getByText('Access control')).toBeInTheDocument()

        // Dashboard options smoke checks
        expect(screen.getByText(/Show PostHog branding/i)).toBeInTheDocument()
    })
})

describe('SharingModal (insight)', () => {
    const fakeInsight: Partial<QueryBasedInsightModel> = {
        id: defaultInsightId,
        short_id: insightShortId,
        name: 'My insight',
    }

    function InsightSharingModalWrapper({ extraProps }: { extraProps?: Partial<SharingModalProps> }): JSX.Element {
        useAvailableFeatures([])
        initKeaTests()
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

        // Dashboard-only options should not be present
        const modalTitle = await screen.findByText('Insight permissions & sharing')
        const modal = modalTitle.closest('[role="dialog"]')
        expect(modal).toBeTruthy()

        expect(within(modal as HTMLElement).queryByText(/Show insight details/i)).toBeNull()
    })
})
