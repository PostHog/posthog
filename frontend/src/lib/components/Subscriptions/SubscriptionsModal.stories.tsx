import React, { useRef } from 'react'
import { ComponentMeta } from '@storybook/react'
import { Subscriptions, SubscriptionsModalProps } from './SubscriptionsModal'
import { AvailableFeature, InsightShortId, Realm, SubscriptionType } from '~/types'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useAvailableFeatures } from '~/mocks/features'
import { uuid } from 'lib/utils'
import { useStorybookMocks } from '~/mocks/browser'

export default {
    title: 'Components/Subscriptions',
    component: Subscriptions,
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'canvas' },
} as ComponentMeta<typeof Subscriptions>

const createSubscription = (args: Partial<SubscriptionType> = {}): SubscriptionType =>
    ({
        id: 1,
        title: 'My example subscription',
        target_type: 'email',
        target_value: 'ben@posthog.com,geoff@other-company.com',
        frequency: 'monthly',
        interval: 2,
        start_date: '2022-01-01T00:09:00',
        byweekday: ['wednesday'],
        bysetpos: 1,
        summary: 'sent every month on the first wednesday',
        ...args,
    } as SubscriptionType)

const Template = (
    args: Partial<SubscriptionsModalProps> & { preflightIssues?: boolean; featureAvailable?: boolean }
): JSX.Element => {
    const { preflightIssues = false, featureAvailable = true, ...props } = args
    const insightShortIdRef = useRef(props.insightShortId || (uuid() as InsightShortId))

    useAvailableFeatures(featureAvailable ? [AvailableFeature.SUBSCRIPTIONS] : [])

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
                              createSubscription(),
                              createSubscription({
                                  title: 'Weekly C-level report',
                                  target_value: 'james@posthog.com',
                                  frequency: 'weekly',
                                  interval: 1,
                              }),
                          ],
            },
            '/api/projects/:id/subscriptions/:subId': createSubscription(),
        },
    })

    return (
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
