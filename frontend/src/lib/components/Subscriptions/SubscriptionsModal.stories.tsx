import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useEffect, useRef, useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { uuid } from 'lib/utils'

import { useStorybookMocks } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { createMockSubscription, mockIntegration, mockSlackChannels } from '~/test/mocks'
import { AvailableFeature, InsightShortId, Realm } from '~/types'

import { SubscriptionsModal, SubscriptionsModalProps } from './SubscriptionsModal'

type StoryArgs = SubscriptionsModalProps & {
    noIntegrations?: boolean
    featureAvailable?: boolean
    aiSummaryAtLimit?: boolean
}

const meta: Meta<StoryArgs> = {
    title: 'Components/Subscriptions',
    component: SubscriptionsModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-31 12:00:00',
    },
    render: (args) => {
        const { noIntegrations = false, featureAvailable = true, aiSummaryAtLimit = false, ...props } = args
        const insightShortIdRef = useRef(props.insightShortId || (uuid() as InsightShortId))
        const [modalOpen, setModalOpen] = useState(false)

        useAvailableFeatures(featureAvailable ? [AvailableFeature.SUBSCRIPTIONS] : [])

        useEffect(() => {
            if (!aiSummaryAtLimit) {
                return
            }
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.HACKATHONS_SUBSCRIPTIONS], {
                [FEATURE_FLAGS.HACKATHONS_SUBSCRIPTIONS]: true,
            })
            // Reset on unmount so the flag doesn't leak into other stories
            // rendered later in the same Storybook session.
            return () => {
                featureFlagLogic.actions.setFeatureFlags([], {
                    [FEATURE_FLAGS.HACKATHONS_SUBSCRIPTIONS]: false,
                })
            }
        }, [aiSummaryAtLimit])

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
                ...(aiSummaryAtLimit
                    ? {
                          '/api/organizations/@current/': {
                              ...MOCK_DEFAULT_ORGANIZATION,
                              is_ai_data_processing_approved: true,
                          },
                      }
                    : {}),
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
                '/api/projects/:id/subscriptions/summary_quota': aiSummaryAtLimit
                    ? { active_count: 10, limit: 10, at_limit: true }
                    : { active_count: 0, limit: 10, at_limit: false },
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

export const SubscriptionAtAISummaryLimit: Story = {
    args: { subscriptionId: 'new', aiSummaryAtLimit: true },
}
