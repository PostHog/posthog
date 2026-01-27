// Action key constants - sync with backend ACTION_REGISTRY
export const ApprovalActionKey = {
    FEATURE_FLAG_ENABLE: 'feature_flag.enable',
    FEATURE_FLAG_DISABLE: 'feature_flag.disable',
    FEATURE_FLAG_UPDATE: 'feature_flag.update',
} as const

export type ApprovalActionKeyType = (typeof ApprovalActionKey)[keyof typeof ApprovalActionKey]

export const APPROVAL_ACTIONS: Record<string, { label: string; description: string }> = {
    [ApprovalActionKey.FEATURE_FLAG_ENABLE]: { label: 'Enable feature flag', description: 'enable this feature flag' },
    [ApprovalActionKey.FEATURE_FLAG_DISABLE]: {
        label: 'Disable feature flag',
        description: 'disable this feature flag',
    },
    [ApprovalActionKey.FEATURE_FLAG_UPDATE]: {
        label: 'Update feature flag',
        description: 'update feature flag fields',
    },
}

export function getApprovalActionLabel(actionKey: string): string {
    return APPROVAL_ACTIONS[actionKey]?.label || actionKey.replace(/[._]/g, ' ')
}

export function getApprovalActionDescription(actionKey: string): string {
    return APPROVAL_ACTIONS[actionKey]?.description || actionKey.replace(/[._]/g, ' ')
}

export const ApprovalResourceType = {
    FEATURE_FLAG: 'feature_flag',
} as const

// Maps resource types to display names and URL builders
const APPROVAL_RESOURCE_CONFIG: Record<string, { label: string; urlBuilder: (id: string) => string }> = {
    [ApprovalResourceType.FEATURE_FLAG]: { label: 'Feature flag', urlBuilder: (id) => `/feature_flags/${id}` },
}

export function getApprovalResourceUrl(actionKey: string, resourceId: string | null): string | null {
    if (!resourceId) {
        return null
    }
    const prefix = actionKey.split('.')[0]
    const config = APPROVAL_RESOURCE_CONFIG[prefix]
    return config ? config.urlBuilder(resourceId) : null
}

export function getApprovalResourceLabel(resourceType: string): string {
    return APPROVAL_RESOURCE_CONFIG[resourceType]?.label || resourceType.replace(/_/g, ' ')
}

export function getApprovalResourceName(resourceType: string, intent: Record<string, any>): string | null {
    switch (resourceType) {
        case ApprovalResourceType.FEATURE_FLAG:
            return intent?.flag_key || null
        default:
            return null
    }
}
