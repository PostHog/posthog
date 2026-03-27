import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { useStorybookMocks } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { examples } from '~/queries/examples'
import { AvailableFeature, InsightShortId, QueryBasedInsightModel } from '~/types'

import { SharingModal, SharingModalProps } from './SharingModal'

const fakeInsight: Partial<QueryBasedInsightModel> = {
    id: 123,
    short_id: 'insight123' as InsightShortId,
    query: examples.InsightTrendsQuery,
}

type StoryArgs = SharingModalProps & { licensed?: boolean; passwordRequired?: boolean }

const meta: Meta<StoryArgs> = {
    title: 'Components/Sharing',
    component: SharingModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    render: (args) => {
        const { licensed = false, passwordRequired = false, ...props } = args
        const [modalOpen, setModalOpen] = useState(false)

        useAvailableFeatures(licensed ? [AvailableFeature.WHITE_LABELLING, AvailableFeature.ADVANCED_PERMISSIONS] : [])

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
                            },
                        }),
                    {}
                ),
                '/api/environments/:id/insights/': { results: [fakeInsight] },
            },
            patch: [
                '/api/environments/:id/insights/:insight_id/sharing/',
                '/api/environments/:id/dashboards/:dashboard_id/sharing/',
                '/api/environments/:id/session_recordings/:recording_id/sharing/',
            ].reduce(
                (acc, url) =>
                    Object.assign(acc, {
                        [url]: (req: any) => {
                            return [
                                200,
                                {
                                    created_at: '2022-06-28T12:30:51.459746Z',
                                    enabled: true,
                                    access_token: '1AEQjQ2xNLGoiyI0UnNlLzOiBZWWMQ',
                                    password_required: passwordRequired,
                                    ...req.body,
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
    args: { title: 'Dashboard permissions', dashboardId: 123 },
    decorators: [
        (Story) => (
            <BindLogic logic={dashboardLogic} props={{ id: 123 }}>
                <Story />
            </BindLogic>
        ),
    ],
}

export const DashboardSharingLicensed: Story = {
    args: { title: 'Dashboard permissions', licensed: true, passwordRequired: true, dashboardId: 123 },
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
