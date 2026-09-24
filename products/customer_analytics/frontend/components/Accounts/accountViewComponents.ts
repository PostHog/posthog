import { FEATURE_FLAGS, type FeatureFlagKey } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import type { AccountExpansionTab } from './accountsExpansionLogic'

export type AccountViewComponentKind = AccountExpansionTab

export interface AccountViewComponentDefinition {
    kind: AccountViewComponentKind
    tagName: string
    label: string
    systemTabId: `system:${AccountViewComponentKind}`
    featureFlag?: FeatureFlagKey
}

export const ACCOUNT_VIEW_COMPONENTS: AccountViewComponentDefinition[] = [
    { kind: 'notes', tagName: 'Notes', label: 'Notes', systemTabId: 'system:notes' },
    {
        kind: 'tasks',
        tagName: 'Tasks',
        label: 'Tasks',
        systemTabId: 'system:tasks',
        featureFlag: FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS,
    },
    { kind: 'users', tagName: 'Users', label: 'Users', systemTabId: 'system:users' },
    {
        kind: 'relationships',
        tagName: 'Relationships',
        label: 'Relationships',
        systemTabId: 'system:relationships',
    },
    {
        kind: 'feature_requests',
        tagName: 'FeatureRequests',
        label: 'Feature requests',
        systemTabId: 'system:feature_requests',
        featureFlag: FEATURE_FLAGS.CUSTOMER_ANALYTICS_FEATURE_REQUESTS,
    },
    { kind: 'usage', tagName: 'Usage', label: 'Usage', systemTabId: 'system:usage' },
    { kind: 'spend', tagName: 'Spend', label: 'Spend', systemTabId: 'system:spend' },
    {
        kind: 'opportunities',
        tagName: 'Opportunities',
        label: 'Opportunities',
        systemTabId: 'system:opportunities',
    },
    {
        kind: 'conversations',
        tagName: 'Conversations',
        label: 'Conversations',
        systemTabId: 'system:conversations',
    },
    {
        kind: 'meetings',
        tagName: 'Meetings',
        label: 'Meetings',
        systemTabId: 'system:meetings',
        featureFlag: FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
    },
    {
        kind: 'event_stream',
        tagName: 'EventStream',
        label: 'Event stream',
        systemTabId: 'system:event_stream',
        featureFlag: FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
    },
]

export function listAvailableAccountViewComponents(featureFlags: FeatureFlagsSet): AccountViewComponentDefinition[] {
    return ACCOUNT_VIEW_COMPONENTS.filter(
        (component) => !component.featureFlag || !!featureFlags[component.featureFlag]
    )
}

export function getAccountViewComponentByKind(
    kind: AccountViewComponentKind
): AccountViewComponentDefinition | undefined {
    return ACCOUNT_VIEW_COMPONENTS.find((component) => component.kind === kind)
}

export function getAccountViewComponentByTag(tagName: string): AccountViewComponentDefinition | undefined {
    return ACCOUNT_VIEW_COMPONENTS.find((component) => component.tagName === tagName)
}

export function getAccountViewComponentBySystemTabId(tabId: string): AccountViewComponentDefinition | undefined {
    return ACCOUNT_VIEW_COMPONENTS.find((component) => component.systemTabId === tabId)
}
