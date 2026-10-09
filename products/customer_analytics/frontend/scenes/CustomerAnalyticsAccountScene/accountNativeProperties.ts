import { cleanDomains, cleanEmails } from '../../components/Accounts/accountEmailMatching'
import { accountsPartialUpdate, accountsRetrieve } from '../../generated/api'
import type { AccountApi, PatchedAccountApi, PatchedAccountApiProperties } from '../../generated/api.schemas'

export const ACCOUNT_ID_FIELDS = [
    { key: 'website_domain', label: 'Website domain', placeholder: 'example.com' },
    { key: 'billing_id', label: 'Billing ID', placeholder: 'e.g. cus_acme_123' },
    { key: 'slack_channel_id', label: 'Slack channel ID', placeholder: 'e.g. C0123456789' },
    { key: 'sfdc_id', label: 'Salesforce ID', placeholder: 'e.g. 0011t00000AbCdEfGhI' },
    { key: 'stripe_customer_id', label: 'Stripe ID', placeholder: 'e.g. cus_acme_123' },
] as const

export const ACCOUNT_LIST_FIELDS = [
    { key: 'email_domains', label: 'Email domains', placeholder: 'example.com' },
    { key: 'known_emails', label: 'Known emails', placeholder: 'jane@example.com' },
] as const

export type AccountNativePropertyKey =
    | (typeof ACCOUNT_ID_FIELDS)[number]['key']
    | (typeof ACCOUNT_LIST_FIELDS)[number]['key']
export type AccountNativePropertyValue = string | string[]
export type AccountNativePropertyPatch = Partial<
    Pick<NonNullable<PatchedAccountApiProperties>, AccountNativePropertyKey>
>

export type AccountTopLevelPatch = Partial<Pick<PatchedAccountApi, 'name' | 'churned_at' | 'ignored_at'>>

export function isAccountNativePropertyKey(key: unknown): key is AccountNativePropertyKey {
    return [...ACCOUNT_ID_FIELDS, ...ACCOUNT_LIST_FIELDS].some((field) => field.key === key)
}

const accountWrites = new Map<string, Promise<unknown>>()

export async function updateAccountNativeProperties(
    projectId: number,
    accountId: string,
    properties: AccountNativePropertyPatch,
    topLevelFields: AccountTopLevelPatch = {}
): Promise<AccountApi> {
    const key = `${projectId}:${accountId}`
    const previous = accountWrites.get(key) ?? Promise.resolve()
    const write = previous
        .catch(() => undefined)
        .then(async (): Promise<AccountApi> => {
            const current = await accountsRetrieve(String(projectId), accountId)
            const changes: AccountNativePropertyPatch = { ...properties }
            for (const { key } of ACCOUNT_ID_FIELDS) {
                if (key === 'stripe_customer_id' && !current.properties?.stripe_customer_id) {
                    delete changes[key]
                } else if (typeof changes[key] === 'string') {
                    changes[key] = changes[key]?.trim() || null
                }
            }
            if (changes.email_domains) {
                changes.email_domains = cleanDomains(changes.email_domains)
            }
            if (changes.known_emails) {
                changes.known_emails = cleanEmails(changes.known_emails)
            }
            // Serialize local editors and merge against a fresh read so another field's edit is not replaced.
            return accountsPartialUpdate(String(projectId), accountId, {
                ...topLevelFields,
                properties: { ...current.properties, ...changes },
            })
        })
    accountWrites.set(key, write)
    try {
        return await write
    } finally {
        if (accountWrites.get(key) === write) {
            accountWrites.delete(key)
        }
    }
}
