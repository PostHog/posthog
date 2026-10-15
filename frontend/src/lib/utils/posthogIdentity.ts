import type { PostHog, Properties } from 'posthog-js'

import type { UserType } from '~/types'

interface PostHogGroup {
    type: string
    key: string
    properties?: Properties
}

interface UserIdentity {
    distinctId: string
    personProperties: Properties
    superProperties: Properties
    groups: PostHogGroup[]
}

/** Feature flags target these person and group properties, so this list also decides what a user's flags can use. */
function userIdentity(user: UserType): UserIdentity {
    const groups: PostHogGroup[] = []
    if (user.team) {
        groups.push({
            type: 'project',
            key: user.team.uuid,
            properties: {
                id: user.team.id,
                uuid: user.team.uuid,
                name: user.team.name,
                ingested_event: user.team.ingested_event,
                is_demo: user.team.is_demo,
                timezone: user.team.timezone,
                instance_tag: user.organization?.metadata?.instance_tag,
            },
        })
    }
    if (user.organization) {
        groups.push({
            type: 'organization',
            key: user.organization.id,
            properties: {
                id: user.organization.id,
                name: user.organization.name,
                slug: user.organization.slug,
                created_at: user.organization.created_at,
                available_product_features: user.organization.available_product_features,
                member_count: user.organization.member_count,
                project_count: user.organization.teams.length,
                ...user.organization.metadata,
            },
        })
        if (user.organization.customer_id) {
            groups.push({ type: 'customer', key: user.organization.customer_id })
        }
    }
    return {
        distinctId: user.distinct_id,
        personProperties: { email: user.anonymize_data ? null : user.email, realm: user.realm },
        superProperties: { is_demo_project: user.team?.is_demo },
        groups,
    }
}

const sentIdentities = new Map<'user' | 'instance', string>()

/**
 * Sends an identity only when it differs from the last one this page sent. posthog-js stores the person
 * and group properties from these calls as the inputs of the next /flags request. The calls also reload
 * flags as a side effect, so reloads stay paused while they run, and the caller loads flags once when
 * this returns true.
 */
function sendIdentityIfChanged(
    posthog: PostHog,
    kind: 'user' | 'instance',
    identity: UserIdentity | PostHogGroup,
    send: () => void
): boolean {
    const fingerprint = JSON.stringify(identity)
    if (sentIdentities.get(kind) === fingerprint) {
        return false
    }
    sentIdentities.set(kind, fingerprint)
    posthog.featureFlags.setReloadingPaused(true)
    try {
        send()
    } finally {
        posthog.featureFlags.setReloadingPaused(false)
    }
    return true
}

/** Returns true when the user's identity changed, which means the flags need a reload. */
export function identifyUserInPostHog(posthog: PostHog, user: UserType): boolean {
    const identity = userIdentity(user)
    return sendIdentityIfChanged(posthog, 'user', identity, () => {
        posthog.identify(identity.distinctId)
        posthog.setPersonProperties(identity.personProperties)
        posthog.register(identity.superProperties)
        for (const group of identity.groups) {
            posthog.group(group.type, group.key, group.properties)
        }
    })
}

/** Returns true when the instance changed, which means the flags need a reload. */
export function identifyInstanceInPostHog(posthog: PostHog, siteUrl: string): boolean {
    const instance: PostHogGroup = { type: 'instance', key: siteUrl, properties: { site_url: siteUrl } }
    return sendIdentityIfChanged(posthog, 'instance', instance, () => {
        posthog.group(instance.type, instance.key, instance.properties)
    })
}
