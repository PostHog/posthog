import React, { useState } from 'react'
import { ComponentMeta } from '@storybook/react'
import { Sharing, SharingModal, SharingModalProps } from './SharingModal'
import { InsightModel, InsightShortId, InsightType, Realm } from '~/types'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useStorybookMocks } from '~/mocks/browser'
import { LemonButton } from '../LemonButton'

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

const Template = (args: Partial<SharingModalProps> & { noIntegrations?: boolean }): JSX.Element => {
    const { noIntegrations = false, ...props } = args
    const [modalOpen, setModalOpen] = useState(false)

    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                realm: Realm.Cloud,
                email_service_available: !noIntegrations,
                site_url: noIntegrations ? 'bad-value' : window.location.origin,
            },
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

export const InsightSharing = (): JSX.Element => {
    return <Template insightShortId={fakeInsight.short_id} insight={fakeInsight} />
}
