import React from 'react'
import { ChatWidget } from '@papercups-io/chat-widget'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { preflightLogic } from 'scenes/PreflightCheck/logic'

export function Papercups(): JSX.Element {
    const { user } = useValues(userLogic)
    const { billing } = useValues(billingLogic)
    const { realm, preflight } = useValues(preflightLogic)

    return (
        <ChatWidget
            accountId="873f5102-d267-4b09-9de0-d6e741e0e076"
            title="Welcome to PostHog"
            subtitle="Ask us anything in the chat window below 😊"
            newMessagePlaceholder="Start typing…"
            primaryColor="#5375ff"
            awayMessage="We'll reply as soon as we're back online. You can check [our help center](https://www.posthog.com/docs) in the meantime."
            greeting="Hi! We'll respond as soon as we can. For additional assistance, please check [our help center](https://www.posthog.com/docs)"
            customer={
                user &&
                preflight && {
                    email: user.email,
                    name: user.first_name,
                    external_id: user.distinct_id,
                    metadata: {
                        user_id: user.uuid,
                        organization_name: user.organization?.name,
                        organization_id: user.organization?.id,
                        organization_plan: billing?.plan?.key,
                        posthog_version: preflight.posthog_version,
                        realm: realm,
                        posthog_domain: location.hostname,
                    },
                }
            }
            showAgentAvailability
        />
    )
}
