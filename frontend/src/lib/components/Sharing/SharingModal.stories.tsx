import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { useStorybookMocks } from '~/mocks/browser'
import { getAvailableProductFeatures, useAvailableFeatures } from '~/mocks/features'
import type { MockResolverInfo } from '~/mocks/utils'
import { examples } from '~/queries/examples'
import { SharingConfigurationSettings } from '~/queries/schema/schema-general'
import { AvailableFeature, InsightShortId, InsightModel } from '~/types'

import { SharingModal, SharingModalProps } from './SharingModal'

const MOCK_ORGANIZATION_LOGO_ID = '0190a3c2-0000-0000-0000-000000000001'
const fakeInsight: Partial<InsightModel> = {
    id: 123,
    short_id: 'insight123' as InsightShortId,
    query: examples.InsightTrendsQuery,
}

type StoryArgs = SharingModalProps & {
    licensed?: boolean
    passwordRequired?: boolean
    sharingSettings?: SharingConfigurationSettings
    organizationHasLogo?: boolean
}

const meta: Meta<StoryArgs> = {
    title: 'Components/Sharing',
    component: SharingModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    render: (args) => {
        const { licensed = false, passwordRequired = false, sharingSettings, organizationHasLogo, ...props } = args
        const [modalOpen, setModalOpen] = useState(false)

        useAvailableFeatures(licensed ? [AvailableFeature.WHITE_LABELLING, AvailableFeature.ACCESS_CONTROL] : [])

        useStorybookMocks({
            get: {
                ...[
                    '/api/environments/:id/insights/:insight_id/sharing/',
                    '/api/environments/:id/dashboards/:dashboard_id/sharing/',
                    '/api/environments/:id/session_recordings/:recording_id/sharing/',
                ].reduce(
                    (acc, url) =>
                        Object.assign(acc, {
                            [url]: {
                                created_at: '2022-06-28T12:30:51.459746Z',
                                enabled: true,
                                access_token: '1AEQjQ2xNLGoiyI0UnNlLzOiBZWWMQ',
                                password_required: passwordRequired,
                                settings: sharingSettings,
                            },
                        }),
                    {}
                ),
                '/api/environments/:id/insights/': { results: [fakeInsight] },
                ...(organizationHasLogo
                    ? {
                          '/api/organizations/@current/': {
                              ...MOCK_DEFAULT_ORGANIZATION,
                              logo_media_id: MOCK_ORGANIZATION_LOGO_ID,
                              available_product_features: getAvailableProductFeatures(),
                          },
                          '/uploaded_media/:id': ({ request }: MockResolverInfo) =>
                              Response.redirect(new URL('/static/not-found-astrohog.png', request.url).toString()),
                      }
                    : {}),
            },
            patch: [
                '/api/environments/:id/insights/:insight_id/sharing/',
                '/api/environments/:id/dashboards/:dashboard_id/sharing/',
                '/api/environments/:id/session_recordings/:recording_id/sharing/',
            ].reduce(
                (acc, url) =>
                    Object.assign(acc, {
                        [url]: async ({ request }: MockResolverInfo) => {
                            const body = (await request.json()) as Record<string, unknown>
                            return [
                                200,
                                {
                                    created_at: '2022-06-28T12:30:51.459746Z',
                                    enabled: true,
                                    access_token: '1AEQjQ2xNLGoiyI0UnNlLzOiBZWWMQ',
                                    password_required: passwordRequired,
                                    ...body,
                                },
                            ]
                        },
                    }),
                {}
            ),
        })

        return (
            <div>
                <div className="bg-default p-2">
                    <SharingModal
                        {...(props as SharingModalProps)}
                        closeModal={() => {
                            // eslint-disable-next-line no-console
                            console.log('close')
                        }}
                        isOpen={true}
                        inline
                    />
                </div>

                <div className="flex justify-center mt-4">
                    <LemonButton onClick={() => setModalOpen(true)} type="primary">
                        Open as Modal
                    </LemonButton>
                </div>

                <SharingModal
                    {...(props as SharingModalProps)}
                    closeModal={() => setModalOpen(false)}
                    isOpen={modalOpen}
                />
            </div>
        )
    },
}
export default meta

type Story = StoryObj<StoryArgs>

export const DashboardSharing: Story = {
    args: { title: 'Share dashboard', dashboardId: 123 },
    decorators: [
        (Story) => (
            <BindLogic logic={dashboardLogic} props={{ id: 123 }}>
                <Story />
            </BindLogic>
        ),
    ],
}

export const DashboardSharingLicensed: Story = {
    args: { title: 'Share dashboard', licensed: true, passwordRequired: true, dashboardId: 123 },
    decorators: [
        (Story) => (
            <BindLogic logic={dashboardLogic} props={{ id: 123 }}>
                <Story />
            </BindLogic>
        ),
    ],
}

export const DashboardSharingCustomBranding: Story = {
    args: {
        title: 'Share dashboard',
        licensed: true,
        dashboardId: 123,
        organizationHasLogo: true,
        sharingSettings: { whitelabel: true, showOrganizationLogo: true },
    },
    decorators: [
        (Story) => (
            <BindLogic logic={dashboardLogic} props={{ id: 123 }}>
                <Story />
            </BindLogic>
        ),
    ],
}

export const InsightSharing: Story = {
    args: {
        title: 'Insight permissions',
        insightShortId: fakeInsight.short_id,
        insight: fakeInsight,
        previewIframe: true,
    },
}

export const InsightSharingLicensed: Story = {
    args: {
        title: 'Insight permissions',
        insightShortId: fakeInsight.short_id,
        insight: fakeInsight,
        licensed: true,
        passwordRequired: true,
        previewIframe: true,
    },
}

export const RecordingSharingLicensed: Story = {
    args: { title: 'Share Recording', recordingId: 'fake-id', licensed: true, previewIframe: true },
}
