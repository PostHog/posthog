import { Meta, StoryObj } from '@storybook/react'
import { useRef, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { uuid } from 'lib/utils'

import { useStorybookMocks } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { createMockSubscription, mockIntegration, mockSlackChannels } from '~/test/mocks'
import { AvailableFeature, InsightShortId, Realm } from '~/types'

import { SubscriptionsModal, SubscriptionsModalProps } from './SubscriptionsModal'

type StoryArgs = SubscriptionsModalProps & { noIntegrations?: boolean; featureAvailable?: boolean }

const meta: Meta<StoryArgs> = {
    title: 'Components/Subscriptions',
    component: SubscriptionsModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-31 12:00:00',
    },
    render: (args) => {
        const { noIntegrations = false, featureAvailable = true, ...props } = args
        const insightShortIdRef = useRef(props.insightShortId || (uuid() as InsightShortId))
        const [modalOpen, setModalOpen] = useState(false)

        useAvailableFeatures(featureAvailable ? [AvailableFeature.SUBSCRIPTIONS] : [])

        useStorybookMocks({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    realm: Realm.Cloud,
                    email_service_available: noIntegrations ? false : true,
                    slack_service: noIntegrations
                        ? { available: false }
                        : { available: true, client_id: 'test-client-id' },
                    site_url: noIntegrations ? 'bad-value' : window.location.origin,
                },
                '/api/environments/:id/subscriptions': {
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
                '/api/environments/:id/subscriptions/:subId': createMockSubscription(),
                '/api/projects/:id/integrations': { results: !noIntegrations ? [mockIntegration] : [] },
                '/api/projects/:id/integrations/:intId/channels': { channels: mockSlackChannels },
            },
        })

        return (
            <div>
                <div className="p-4 bg-border">
                    <SubscriptionsModal
                        {...(props as SubscriptionsModalProps)}
                        closeModal={() => {
                            // eslint-disable-next-line no-console
                            console.log('close')
                        }}
                        insightShortId={insightShortIdRef.current}
                        isOpen={true}
                        inline
                    />
                </div>

                <div className="flex justify-center mt-4">
                    <LemonButton onClick={() => setModalOpen(true)} type="primary">
                        Open as Modal
                    </LemonButton>
                </div>

                <SubscriptionsModal
                    {...(props as SubscriptionsModalProps)}
                    closeModal={() => setModalOpen(false)}
                    insightShortId={insightShortIdRef.current}
                    isOpen={modalOpen}
                />
            </div>
        )
    },
}
export default meta

type Story = StoryObj<StoryArgs>

export const Subscriptions_: Story = {}

export const SubscriptionsEmpty: Story = {
    args: { insightShortId: 'empty' as InsightShortId },
}

export const SubscriptionsNew: Story = {
    args: { subscriptionId: 'new' },
}

export const SubscriptionNoIntegrations: Story = {
    args: { subscriptionId: 'new', noIntegrations: true },
}

export const SubscriptionsEdit: Story = {
    args: { subscriptionId: 1 },
}

export const SubscriptionsUnavailable: Story = {
    args: { featureAvailable: false },
}
