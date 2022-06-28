import React, { useRef, useState } from 'react'
import { ComponentMeta } from '@storybook/react'
import { Sharing, SharingModal, SharingModalProps } from './SharingModal'
import { InsightShortId, Realm } from '~/types'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { uuid } from 'lib/utils'
import { useStorybookMocks } from '~/mocks/browser'
import { LemonButton } from '../LemonButton'
import { createMockSubscription, mockIntegration, mockSlackChannels } from '~/test/mocks'

export default {
    title: 'Components/Sharing',
    component: Sharing,
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'canvas' },
} as ComponentMeta<typeof Sharing>

const Template = (args: Partial<SharingModalProps> & { noIntegrations?: boolean }): JSX.Element => {
    const { noIntegrations = false, ...props } = args
    const insightShortIdRef = useRef(props.insightShortId || (uuid() as InsightShortId))
    const [modalOpen, setModalOpen] = useState(false)

    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                realm: Realm.Cloud,
                email_service_available: !noIntegrations,
                site_url: noIntegrations ? 'bad-value' : window.location.origin,
            },
            '/api/projects/:id/Sharing': {
                results:
                    insightShortIdRef.current === 'empty'
                        ? []
                        : [
                              createMockSubscription(),
                              createMockSubscription({
                                  title: 'Weekly C-level report',
                                  target_value: 'james@posthog.com',
                                  frequency: 'weekly',
                                  interval: 1,
                              }),
                              createMockSubscription({
                                  title: 'Daily Slack report',
                                  target_type: 'slack',
                                  target_value: 'C123|#general',
                                  frequency: 'weekly',
                                  interval: 1,
                              }),
                          ],
            },
            '/api/projects/:id/Sharing/:subId': createMockSubscription(),
            '/api/projects/:id/integrations': { results: !noIntegrations ? [mockIntegration] : [] },
            '/api/projects/:id/integrations/:intId/channels': { channels: mockSlackChannels },
        },
    })

    return (
        <div>
            <div className="LemonModal">
                <div className="border-all ant-modal-body" style={{ width: 650, margin: '20px auto' }}>
                    <Sharing
                        {...(props as SharingModalProps)}
                        closeModal={() => console.log('close')}
                        insightShortId={insightShortIdRef.current}
                        visible={true}
                    />
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
                insightShortId={insightShortIdRef.current}
                visible={modalOpen}
            />
        </div>
    )
}

export const Sharing_ = (): JSX.Element => {
    return <Template />
}

export const SharingEmpty = (): JSX.Element => {
    return <Template insightShortId={'empty' as InsightShortId} />
}
