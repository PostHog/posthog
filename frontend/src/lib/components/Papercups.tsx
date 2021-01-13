import React from 'react'
import { ChatWidget } from '@papercups-io/chat-widget'
import { UserType } from '~/types'

export function Papercups({ user }: { user: UserType | null }): JSX.Element {
    return (
        <ChatWidget
            accountId="873f5102-d267-4b09-9de0-d6e741e0e076"
            title="Welcome to PostHog"
            subtitle="Ask us anything in the chat window below 😊"
            newMessagePlaceholder="Start typing…"
            primaryColor="#5375ff"
            greeting="Hi! Send us a message and we'll respond as soon as we can."
            customer={
                user && {
                    email: user.email,
                    name: user.name,
                    external_id: user.distinct_id,
                    metadata: {
                        user_id: user.id,
                        organization_name: user.organization?.name,
                        organization_id: user.organization?.id,
                        organization_plan: user.organization?.billing_plan,
                        posthog_version: user.posthog_version,
                        posthog_domain: location.hostname,
                    },
                }
            }
            showAgentAvailability
        />
    )
}
