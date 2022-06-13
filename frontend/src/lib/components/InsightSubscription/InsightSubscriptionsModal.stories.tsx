import React, { useEffect, useState } from 'react'
import { ComponentStory, ComponentMeta } from '@storybook/react'
import { InsightSubscriptionsModal } from './InsightSubscriptionsModal'
import { LemonButton } from '../LemonButton'
import { InsightShortId, Realm, SubscriptionType } from '~/types'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { insightSubscriptionLogic } from './insightSubscriptionLogic'
import { insightSubscriptionsLogic } from './insightSubscriptionsLogic'

export default {
    title: 'Components/Subscription Modal',
    component: InsightSubscriptionsModal,
} as ComponentMeta<typeof InsightSubscriptionsModal>

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
        ...args,
    } as SubscriptionType)

const Template: ComponentStory<typeof InsightSubscriptionsModal> = (args) => {
    const [isOpen, setIsOpen] = useState(false)

    const { preflightIssues = false, ...props } = args

    useEffect(() => {
        const subsLogic = insightSubscriptionsLogic({
            insightShortId: props.insightShortId || ('123' as InsightShortId),
        })
        subsLogic.unmount()
        subsLogic.mount()

        setTimeout(() => {
            console.log({ props })
            if (props.insightShortId === 'empty') {
                console.log('HERE', subsLogic)
                subsLogic.actions.loadSubscriptionsSuccess([])
            } else {
                subsLogic.actions.loadSubscriptionsSuccess([
                    createSubscription(),
                    createSubscription({
                        title: 'Weekly C-level report',
                        target_value: 'james@posthog.com',
                        frequency: 'weekly',
                        interval: 1,
                    }),
                ])
            }

            if (typeof args.subscriptionId === 'number') {
                const subLogic = insightSubscriptionLogic({
                    insightShortId: '123' as InsightShortId,
                    id: args.subscriptionId,
                })

                subLogic.mount()
                subLogic.actions.loadSubscriptionSuccess(createSubscription())
            }
            preflightLogic().actions.loadPreflightSuccess({
                ...preflightJson,
                realm: Realm.Cloud,
                email_service_available: preflightIssues ? false : true,
                site_url: preflightIssues ? 'bad-value' : window.location.origin,
            })
        }, 1)
    }, [args])

    const _setIsOpen = (open: boolean): void => {
        setIsOpen(open)
    }

    return (
        <>
            <LemonButton type="primary" onClick={() => _setIsOpen(true)}>
                Show Subscriptions
            </LemonButton>
            <InsightSubscriptionsModal
                {...props}
                insightShortId={'123' as InsightShortId}
                visible={isOpen}
                closeModal={() => _setIsOpen(false)}
            />
        </>
    )
}

export const InsightSubscriptionsModal_ = Template.bind({})
InsightSubscriptionsModal_.args = {}

export const InsightSubscriptionsModalEmpty = Template.bind({})
InsightSubscriptionsModalEmpty.args = {
    insightShortId: 'empty' as InsightShortId,
}

export const InsightSubscriptionsModalNew_ = Template.bind({})
InsightSubscriptionsModalNew_.args = {
    subscriptionId: 'new',
}

export const InsightSubscriptionsModalNewEmailDisabled = Template.bind({})
InsightSubscriptionsModalNewEmailDisabled.args = {
    subscriptionId: 'new',
    preflightIssues: true,
}

export const InsightSubscriptionsModalEdit = Template.bind({})
InsightSubscriptionsModalEdit.args = {
    subscriptionId: 1,
}
