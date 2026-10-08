import { IconBuilding } from '@posthog/icons'
import type { LemonTagType } from '@posthog/lemon-ui'

import { getEntryAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { GroupQueryResult } from 'lib/utils/groups'
import { PLACEHOLDER_HREF } from 'lib/utils/navigateToHref'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { getTreeItemsProducts } from '~/products'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { FileSystemIconColor, GroupTypeIndex, SearchResponse } from '~/types'

import type { TicketApi } from 'products/conversations/frontend/generated/api.schemas'
import { getAccountStatusTags } from 'products/customer_analytics/frontend/components/Accounts/accountStatusTags'
import type { AccountApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { filterSearchItems } from './utils'

/** Safely extract a string — returns undefined for objects/arrays to avoid rendering [object Object]. */
const safeString = (val: unknown): string | undefined => (typeof val === 'string' ? val : undefined)

// Types for command search results
export interface SearchItem {
    id: string
    name: string
    displayName?: string
    category: string
    productCategory?: string | null
    href?: string
    /** Action invoked when the item is selected. Use for items that trigger something
     * other than navigation (e.g. logging out). Consumers should prefer `onSelect` over `href`. */
    onSelect?: () => void
    icon?: React.ReactNode
    lastViewedAt?: string | null
    groupNoun?: string | null
    itemType?: string | null
    searchKeywords?: string[]
    hiddenSearchText?: string
    matchedSearchKeyword?: string | null
    parentName?: string
    record?: Record<string, unknown>
    rank?: number | null // PostgreSQL full-text search rank (from unified search API)
    /** When set, the item is shown greyed out and non-clickable, with this reason as tooltip
     * (e.g. the user has no access to the product or resource). */
    disabledReason?: string
    /** Status tags rendered after the name, e.g. "Churned" on an account. */
    badges?: { label: string; type: LemonTagType; tooltip?: string }[]
}

let cachedProductIconColorByType: Map<string, FileSystemIconColor> | null = null
let cachedProductDisplayLabelByPath: Map<string, string> | null = null
let cachedProductIconTypeByPath: Map<string, string> | null = null

const getProductIconColorByType = (): Map<string, FileSystemIconColor> => {
    if (cachedProductIconColorByType === null) {
        cachedProductIconColorByType = new Map()
        for (const product of getTreeItemsProducts()) {
            const key = product.type || product.iconType
            if (key && product.iconColor) {
                cachedProductIconColorByType.set(key, product.iconColor)
            }
        }
    }
    return cachedProductIconColorByType
}

const getProductDisplayLabelByPath = (): Map<string, string> => {
    if (cachedProductDisplayLabelByPath === null) {
        cachedProductDisplayLabelByPath = new Map()
        for (const product of getTreeItemsProducts()) {
            if (product.displayLabel) {
                cachedProductDisplayLabelByPath.set(product.path, product.displayLabel)
            }
        }
    }
    return cachedProductDisplayLabelByPath
}

const getProductIconTypeByPath = (): Map<string, string> => {
    if (cachedProductIconTypeByPath === null) {
        cachedProductIconTypeByPath = new Map()
        for (const product of getTreeItemsProducts()) {
            const iconType = product.type || product.iconType
            if (iconType) {
                cachedProductIconTypeByPath.set(product.path, iconType)
            }
        }
    }
    return cachedProductIconTypeByPath
}

export const fileSystemEntryToSearchItem = (
    item: FileSystemEntry,
    overrides: { id: string; category: string; searchKeywords?: string[] }
): SearchItem => {
    const name = splitPath(item.path).pop()
    const itemName = name ? unescapePath(name) : item.path
    const displayName = getProductDisplayLabelByPath().get(itemName)
    // Older starred shortcuts (e.g. Logs, Web analytics) were saved with a blank (empty-string)
    // type because their product only defines `iconType`. The `||` (not `??`) is deliberate: an
    // empty string must fall through to the product registry, keyed by name, so the icon resolves.
    const itemType = item.type || getProductIconTypeByPath().get(itemName) || null
    const productIconColor = itemType ? getProductIconColorByType().get(itemType) : undefined
    return {
        name: itemName,
        displayName,
        href: item.href || PLACEHOLDER_HREF,
        lastViewedAt: item.last_viewed_at ?? null,
        itemType,
        record: { ...item, iconColor: productIconColor },
        disabledReason: getEntryAccessDisabledReason(item),
        ...overrides,
    }
}

/** Maps one unified search result to a search item. */
export const unifiedSearchResultToSearchItem = (result: SearchResponse['results'][number]): SearchItem => {
    let name = result.result_id
    let href = ''

    switch (result.type) {
        case 'insight':
            name = safeString(result.extra_fields.name) || result.result_id
            href = `/insights/${result.result_id}`
            break
        case 'dashboard':
            name = safeString(result.extra_fields.name) || result.result_id
            href = `/dashboard/${result.result_id}`
            break
        case 'feature_flag':
            name = safeString(result.extra_fields.key) || result.result_id
            href = `/feature_flags/${result.result_id}`
            break
        case 'experiment':
            name = safeString(result.extra_fields.name) || result.result_id
            href = `/experiments/${result.result_id}`
            break
        case 'early_access_feature':
            name = safeString(result.extra_fields.name) || result.result_id
            href = `/early_access_features/${result.result_id}`
            break
        case 'hog_flow':
            name = safeString(result.extra_fields.name) || result.result_id
            href = `/workflows/${result.result_id}/workflow`
            break
        case 'survey':
            name = safeString(result.extra_fields.name) || result.result_id
            href = `/surveys/${result.result_id}`
            break
        case 'notebook':
            name = safeString(result.extra_fields.title) || result.result_id
            href = `/notebooks/${result.result_id}`
            break
        case 'cohort':
            name = safeString(result.extra_fields.name) || result.result_id
            href = `/cohorts/${result.result_id}`
            break
        case 'action':
            name = safeString(result.extra_fields.name) || result.result_id
            href = `/data-management/actions/${result.result_id}`
            break
        case 'event_definition':
            name = safeString(result.extra_fields.name) || result.result_id
            href = `/data-management/events/${result.result_id}`
            break
        case 'property_definition':
            name = safeString(result.extra_fields.name) || result.result_id
            href = `/data-management/properties/${result.result_id}`
            break
    }

    return {
        id: `${result.type}-${result.result_id}`,
        name,
        category: result.type,
        href,
        itemType: result.type,
        rank: result.rank,
        disabledReason: getEntryAccessDisabledReason(result),
        record: {
            type: result.type,
            ...result.extra_fields,
        },
    }
}

export const accountToSearchItem = (account: AccountApi): SearchItem => {
    const displayName = account.name || account.external_id || account.id
    return {
        id: `account-${account.id}`,
        name: displayName,
        displayName,
        category: 'accounts',
        href: urls.customerAnalyticsAccount(account.id),
        icon: <IconBuilding />,
        itemType: 'account',
        record: { type: 'account', id: account.id },
        badges: getAccountStatusTags(account).map(({ label, type, dateLabel }) => ({
            label,
            type,
            tooltip: dateLabel,
        })),
    }
}

export const ticketToSearchItem = (ticket: TicketApi): SearchItem => {
    // Only email tickets carry a subject, so a Slack or widget ticket falls back to
    // its latest message — the only line of it that reads as a title. The number
    // leads either way: it is how support refers to a ticket everywhere else, and
    // it is what someone who typed a number is looking to confirm.
    const subject = ticket.email_subject || ticket.last_message_text || 'Untitled ticket'
    const displayName = `#${ticket.ticket_number} ${subject}`
    return {
        id: `ticket-${ticket.id}`,
        name: displayName,
        displayName,
        category: 'tickets',
        // The detail scene redirects a UUID to the ticket-number URL, so linking
        // there directly saves the row a redirect.
        href: urls.supportTicketDetail(ticket.ticket_number),
        itemType: 'conversations',
        // Rendered as the row's muted trailing text: which tickets are still open
        // is the first thing a support agent reads off a list of matches.
        productCategory: ticket.status ? capitalizeFirstLetter(ticket.status.replace(/_/g, ' ')) : null,
        record: { type: 'conversations', id: ticket.id, ticketNumber: ticket.ticket_number },
    }
}

/** "Create new" items match when every word is "new"/"create" or appears in the item's name, type, or path. */
const LEADING_CREATE_WORD = /^\s*create\b/i

/** "Create new" items match on their name, type and path, with a leading "create" read as "new". */
export const filterNewItems = (newItems: SearchItem[], search: string): SearchItem[] =>
    filterSearchItems(newItems, search.replace(LEADING_CREATE_WORD, 'new'))

/** Structural, so a person from the legacy API and one from the generated client both fit. */
interface SearchablePerson {
    uuid: string
    distinct_ids?: readonly string[]
    properties?: unknown
}

export const personToSearchItem = (person: SearchablePerson): SearchItem => {
    const personId = person.distinct_ids?.[0] || person.uuid
    const properties = (person.properties ?? {}) as Record<string, unknown>
    const displayName = safeString(properties.email) || safeString(properties.name) || String(personId)
    return {
        id: `person-${person.uuid}`,
        name: displayName,
        displayName,
        category: 'persons',
        href: urls.personByUUID(person.uuid),
        itemType: 'person',
        record: { type: 'person', ref: person.uuid, uuid: person.uuid, distinctIds: person.distinct_ids },
    }
}

export const groupToSearchItem = (
    group: GroupQueryResult,
    groupTypeIndex: GroupTypeIndex,
    noun: string
): SearchItem => {
    const display = group.group_properties?.name || group.group_key || String(group.group_key)
    return {
        id: `group-${groupTypeIndex}-${group.group_key}`,
        name: `${noun}: ${display}`,
        displayName: display,
        category: 'groups',
        href: `/groups/${groupTypeIndex}/${encodeURIComponent(group.group_key)}`,
        groupNoun: noun,
        itemType: 'group',
        record: {
            type: 'group',
            ref: `${groupTypeIndex}:${group.group_key}`,
            groupTypeIndex,
            groupKey: group.group_key,
            groupNoun: noun,
        },
    }
}
