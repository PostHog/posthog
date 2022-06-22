import React, { useRef, useState } from 'react'
import { ComponentMeta } from '@storybook/react'
import { Subscriptions, SubscriptionsModal, SubscriptionsModalProps } from './SubscriptionsModal'
import { AvailableFeature, InsightShortId, Realm } from '~/types'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useAvailableFeatures } from '~/mocks/features'
import { uuid } from 'lib/utils'
import { useFeatureFlags, useStorybookMocks } from '~/mocks/browser'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from '../LemonButton'
import { createMockSubscription, mockIntegration, mockSlackChannels } from '~/test/mocks'

export default {
    title: 'Components/Subscriptions',
    component: Subscriptions,
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'canvas' },
} as ComponentMeta<typeof Subscriptions>

const Template = (
    args: Partial<SubscriptionsModalProps> & { preflightIssues?: boolean; featureAvailable?: boolean }
): JSX.Element => {
    const { preflightIssues = false, featureAvailable = true, ...props } = args
    const insightShortIdRef = useRef(props.insightShortId || (uuid() as InsightShortId))
    const [modalOpen, setModalOpen] = useState(false)

    useAvailableFeatures(featureAvailable ? [AvailableFeature.SUBSCRIPTIONS] : [])
    useFeatureFlags([FEATURE_FLAGS.SUBSCRIPTIONS_SLACK])

    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                realm: Realm.Cloud,
                email_service_available: preflightIssues ? false : true,
                site_url: preflightIssues ? 'bad-value' : window.location.origin,
            },
            '/api/projects/:id/subscriptions': {
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
            '/api/projects/:id/subscriptions/:subId': createMockSubscription(),
            '/api/projects/:id/integrations': { results: [mockIntegration] },
            '/api/projects/:id/integrations/:intId/channels': { channels: mockSlackChannels },
        },
    })

    return (
        <div>
            <div className="LemonModal">
                <div className="border-all ant-modal-body" style={{ width: 650, margin: '20px auto' }}>
                    <Subscriptions
                        {...(props as SubscriptionsModalProps)}
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

            <SubscriptionsModal
                {...(props as SubscriptionsModalProps)}
                closeModal={() => setModalOpen(false)}
                insightShortId={insightShortIdRef.current}
                visible={modalOpen}
            />
        </div>
    )
}

export const Subscriptions_ = (): JSX.Element => {
    return <Template />
}

export const SubscriptionsEmpty = (): JSX.Element => {
    return <Template insightShortId={'empty' as InsightShortId} />
}

export const SubscriptionsNew = (): JSX.Element => {
    return <Template subscriptionId={'new'} />
}

export const SubscriptionsNewEmailDisabled = (): JSX.Element => {
    return <Template subscriptionId={'new'} preflightIssues={true} />
}

export const SubscriptionsEdit = (): JSX.Element => {
    return <Template subscriptionId={1} />
}

export const SubscriptionsUnavailable = (): JSX.Element => {
    return <Template featureAvailable={false} />
}
