import { validate as isUuid } from 'uuid'

import type { AccountViewTileConfig } from '../../components/Accounts/accountViewTileConfig'
import type { PinnedAccountPropertyApi } from '../../generated/api.schemas'
import { AccountNativePropertyKey, isAccountNativePropertyKey } from './accountNativeProperties'
import { MAX_PINNED_ACCOUNT_PROPERTIES } from './components/accountPropertyTypes'

export type AccountWidgetPropertyReference =
    | PinnedAccountPropertyApi
    | { kind: 'account'; key: AccountNativePropertyKey }

export function getAccountWidgetPropertyKey(reference: AccountWidgetPropertyReference): string {
    return reference.kind === 'account'
        ? `account:${reference.key}`
        : `${reference.kind === 'custom_property' ? 'custom' : 'relationship'}:${reference.id}`
}

export function getAccountWidgetProperties(
    config: AccountViewTileConfig | undefined
): AccountWidgetPropertyReference[] {
    if (!Array.isArray(config?.properties)) {
        return []
    }
    const references: AccountWidgetPropertyReference[] = []
    const seen = new Set<string>()
    for (const item of config.properties) {
        if (!item || typeof item !== 'object' || Array.isArray(item)) {
            continue
        }
        let reference: AccountWidgetPropertyReference
        if (item.kind === 'account' && isAccountNativePropertyKey(item.key)) {
            reference = { kind: 'account', key: item.key }
        } else if (
            (item.kind === 'custom_property' || item.kind === 'relationship') &&
            typeof item.id === 'string' &&
            isUuid(item.id)
        ) {
            reference = { kind: item.kind, id: item.id.toLowerCase() }
        } else {
            continue
        }
        const key = getAccountWidgetPropertyKey(reference)
        if (!seen.has(key) && references.length < MAX_PINNED_ACCOUNT_PROPERTIES) {
            references.push(reference)
            seen.add(key)
        }
    }
    return references
}

export function accountWidgetKeysToReferences(keys: string[]): AccountWidgetPropertyReference[] {
    return getAccountWidgetProperties({
        properties: keys.map((key) => {
            const [kind, id] = key.split(':')
            return kind === 'account' ? { kind, key: id } : { kind: kind === 'custom' ? 'custom_property' : kind, id }
        }),
    })
}
