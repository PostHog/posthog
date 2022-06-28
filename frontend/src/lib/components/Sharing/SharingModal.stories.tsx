import React, { useState } from 'react'
import { ComponentMeta } from '@storybook/react'
import { Sharing, SharingModal, SharingModalProps } from './SharingModal'
import { AvailableFeature, InsightModel, InsightShortId, InsightType } from '~/types'
import { useStorybookMocks } from '~/mocks/browser'
import { LemonButton } from '../LemonButton'
import { useAvailableFeatures } from '~/mocks/features'

const fakeInsight: Partial<InsightModel> = {
    id: 123,
    short_id: 'insight123' as InsightShortId,
    filters: { insight: InsightType.TRENDS },
}

export default {
    title: 'Components/Sharing',
    component: Sharing,
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'canvas' },
} as ComponentMeta<typeof Sharing>

const Template = (args: Partial<SharingModalProps> & { licensed?: boolean }): JSX.Element => {
    const { licensed = false, ...props } = args
    const [modalOpen, setModalOpen] = useState(false)

    useAvailableFeatures(licensed ? [AvailableFeature.WHITE_LABELLING] : [])

    useStorybookMocks({
        get: {
            '/api/projects/:id/insights/:insight_id/sharing/': {
                created_at: '2022-06-28T12:30:51.459746Z',
                enabled: true,
                access_token: '1AEQjQ2xNLGoiyI0UnNlLzOiBZWWMQ',
            },
            '/api/projects/:id/insights/': { results: [fakeInsight] },
            '/api/projects/:id/dashboards/:dashboard_id/sharing/': {
                created_at: '2022-06-28T12:30:51.459746Z',
                enabled: true,
                access_token: '1AEQjQ2xNLGoiyI0UnNlLzOiBZWWMQ',
            },
        },
        patch: {
            '/api/projects/:id/insights/:otherId/sharing/': (req: any) => {
                return [
                    200,
                    {
                        created_at: '2022-06-28T12:30:51.459746Z',
                        enabled: true,
                        access_token: '1AEQjQ2xNLGoiyI0UnNlLzOiBZWWMQ',
                        ...(req.body as any),
                    },
                ]
            },

            '/api/projects/:id/dashboards/:otherId/sharing/': (req: any) => {
                return [
                    200,
                    {
                        created_at: '2022-06-28T12:30:51.459746Z',
                        enabled: true,
                        access_token: '1AEQjQ2xNLGoiyI0UnNlLzOiBZWWMQ',
                        ...(req.body as any),
                    },
                ]
            },
        },
    })

    return (
        <div>
            <div className="LemonModal">
                <div className="border-all ant-modal-body" style={{ width: 650, margin: '20px auto' }}>
                    <Sharing {...(props as SharingModalProps)} closeModal={() => console.log('close')} visible={true} />
                </div>
            </div>

            <div className="flex justify-center mt">
                <LemonButton onClick={() => setModalOpen(true)} type="primary">
                    Open as Modal
                </LemonButton>
            </div>

            <SharingModal
                {...(props as SharingModalProps)}
                closeModal={() => setModalOpen(false)}
                visible={modalOpen}
            />
        </div>
    )
}

export const DashboardSharing = (): JSX.Element => {
    return <Template dashboardId={123} />
}

export const DashboardSharingLicensed = (): JSX.Element => {
    return <Template licensed dashboardId={123} />
}

export const InsightSharing = (): JSX.Element => {
    return <Template insightShortId={fakeInsight.short_id} insight={fakeInsight} />
}

export const InsightSharingLicensed = (): JSX.Element => {
    return <Template insightShortId={fakeInsight.short_id} insight={fakeInsight} licensed />
}
