import { Meta } from '@storybook/react'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useState } from 'react'

import { useStorybookMocks } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { AvailableFeature, InsightModel, InsightShortId, InsightType } from '~/types'

import { SharingModal, SharingModalProps } from './SharingModal'

const fakeInsight: Partial<InsightModel> = {
    id: 123,
    short_id: 'insight123' as InsightShortId,
    filters: { insight: InsightType.TRENDS },
}

const meta: Meta<typeof SharingModal> = {
    title: 'Components/Sharing',
    component: SharingModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

const Template = (args: Partial<SharingModalProps> & { licensed?: boolean }): JSX.Element => {
    const { licensed = false, ...props } = args
    const [modalOpen, setModalOpen] = useState(false)

    useAvailableFeatures(licensed ? [AvailableFeature.WHITE_LABELLING] : [])

    useStorybookMocks({
        get: {
            ...[
                '/api/projects/:id/insights/:insight_id/sharing/',
                '/api/projects/:id/dashboards/:dashboard_id/sharing/',
                '/api/projects/:id/session_recordings/:recording_id/sharing/',
            ].reduce(
                (acc, url) => ({
                    ...acc,
                    [url]: {
                        created_at: '2022-06-28T12:30:51.459746Z',
                        enabled: true,
                        access_token: '1AEQjQ2xNLGoiyI0UnNlLzOiBZWWMQ',
                    },
                }),
                {}
            ),
            '/api/projects/:id/insights/': { results: [fakeInsight] },
        },
        patch: {
            ...[
                '/api/projects/:id/insights/:insight_id/sharing/',
                '/api/projects/:id/dashboards/:dashboard_id/sharing/',
                '/api/projects/:id/session_recordings/:recording_id/sharing/',
            ].reduce(
                (acc, url) => ({
                    ...acc,
                    [url]: (req: any) => {
                        return [
                            200,
                            {
                                created_at: '2022-06-28T12:30:51.459746Z',
                                enabled: true,
                                access_token: '1AEQjQ2xNLGoiyI0UnNlLzOiBZWWMQ',
                                ...req.body,
                            },
                        ]
                    },
                }),
                {}
            ),
        },
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

            <SharingModal {...(props as SharingModalProps)} closeModal={() => setModalOpen(false)} isOpen={modalOpen} />
        </div>
    )
}

export const DashboardSharing = (): JSX.Element => {
    return <Template title="Dashboard permissions" dashboardId={123} />
}

export const DashboardSharingLicensed = (): JSX.Element => {
    return <Template title="Dashboard permissions" licensed dashboardId={123} />
}

export const InsightSharing = (): JSX.Element => {
    return (
        <Template
            title="Insight permissions"
            insightShortId={fakeInsight.short_id}
            insight={fakeInsight}
            previewIframe
        />
    )
}

export const InsightSharingLicensed = (): JSX.Element => {
    return (
        <Template
            title="Insight permissions"
            insightShortId={fakeInsight.short_id}
            insight={fakeInsight}
            licensed
            previewIframe
        />
    )
}

export const RecordingSharingLicensed = (): JSX.Element => {
    return <Template title="Share Recording" recordingId={'fake-id'} licensed previewIframe />
}
