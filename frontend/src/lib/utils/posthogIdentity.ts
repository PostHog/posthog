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

/**
 * Feature flags target these person and group properties, so this list also decides what a user's flags can use.
 * `_flag_identity` in `posthog/utils.py` builds the same inputs for the server flag bootstrap. Change both together.
 */
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
 * and group properties from these calls as the inputs of the next /flags request. The calls schedule
 * flag reloads, and posthog-js debounces all reloads made in one task into one /flags request, so the
 * caller can reload flags after this returns true without a second request.
 */
function sendIdentityIfChanged<T extends UserIdentity | PostHogGroup>(
    kind: 'user' | 'instance',
    identity: T,
    send: (identity: T) => void
): boolean {
    const fingerprint = JSON.stringify(identity)
    if (sentIdentities.get(kind) === fingerprint) {
        return false
    }
    send(identity)
    sentIdentities.set(kind, fingerprint)
    return true
}

/** Returns true when the user's identity changed, which means the flags need a reload. */
export function identifyUserInPostHog(posthog: PostHog, user: UserType): boolean {
    return sendIdentityIfChanged('user', userIdentity(user), (identity) => {
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
    return sendIdentityIfChanged('instance', instance, (group) => {
        posthog.group(group.type, group.key, group.properties)
    })
}
