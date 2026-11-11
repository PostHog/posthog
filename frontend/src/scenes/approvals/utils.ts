// Action key constants - sync with backend ACTION_REGISTRY
export const ApprovalActionKey = {
    FEATURE_FLAG_ENABLE: 'feature_flag.enable',
    FEATURE_FLAG_DISABLE: 'feature_flag.disable',
    FEATURE_FLAG_UPDATE: 'feature_flag.update',
    EXPERIMENT_LAUNCH: 'experiment.launch',
    EXPERIMENT_PAUSE: 'experiment.pause',
    EXPERIMENT_UPDATE: 'experiment.update',
} as const

// Actions whose policy can limit approval to some changes. Saving any other action drops its conditions.
export const CONDITIONAL_APPROVAL_ACTIONS: ReadonlySet<string> = new Set([
    ApprovalActionKey.FEATURE_FLAG_UPDATE,
    ApprovalActionKey.EXPERIMENT_UPDATE,
])

// Experiment actions govern an experiment's flag only once the organization scopes policies by flag owner.
export const EXPERIMENT_APPROVAL_ACTIONS: ReadonlySet<string> = new Set([
    ApprovalActionKey.EXPERIMENT_LAUNCH,
    ApprovalActionKey.EXPERIMENT_PAUSE,
    ApprovalActionKey.EXPERIMENT_UPDATE,
])

export type ApprovalActionKeyType = (typeof ApprovalActionKey)[keyof typeof ApprovalActionKey]

export type ApprovalContext = 'feature_flag' | 'experiment'

interface ApprovalActionConfig {
    label: string
    description: string
    contextDescriptions?: Partial<Record<ApprovalContext, string>>
}

export const APPROVAL_ACTIONS: Record<string, ApprovalActionConfig> = {
    [ApprovalActionKey.FEATURE_FLAG_ENABLE]: {
        label: 'Enable feature flag',
        description: 'enable this feature flag',
        contextDescriptions: { experiment: 'resume this experiment' },
    },
    [ApprovalActionKey.FEATURE_FLAG_DISABLE]: {
        label: 'Disable feature flag',
        description: 'disable this feature flag',
        contextDescriptions: { experiment: 'pause this experiment' },
    },
    [ApprovalActionKey.FEATURE_FLAG_UPDATE]: {
        label: 'Update feature flag',
        description: "change this feature flag's release conditions or rollout",
        contextDescriptions: { experiment: 'update this experiment' },
    },
    [ApprovalActionKey.EXPERIMENT_LAUNCH]: {
        label: 'Launch experiment',
        description: 'launch this experiment',
    },
    [ApprovalActionKey.EXPERIMENT_PAUSE]: {
        label: 'Pause experiment',
        description: 'pause this experiment',
    },
    [ApprovalActionKey.EXPERIMENT_UPDATE]: {
        label: 'Update experiment',
        description: "change this experiment's rollout or variant split, or ship a winning variant",
    },
}

export function getApprovalActionLabel(actionKey: string): string {
    return APPROVAL_ACTIONS[actionKey]?.label || actionKey.replace(/[._]/g, ' ')
}

export function getApprovalActionDescription(actionKey: string, context?: ApprovalContext): string {
    const action = APPROVAL_ACTIONS[actionKey]
    if (!action) {
        return actionKey.replace(/[._]/g, ' ')
    }
    if (context && action.contextDescriptions?.[context]) {
        return action.contextDescriptions[context]
    }
    return action.description
}

export const ApprovalResourceType = {
    FEATURE_FLAG: 'feature_flag',
} as const

// Maps resource types to display names and URL builders
const APPROVAL_RESOURCE_CONFIG: Record<string, { label: string; urlBuilder: (id: string) => string }> = {
    [ApprovalResourceType.FEATURE_FLAG]: { label: 'Feature flag', urlBuilder: (id) => `/feature-flags/${id}` },
}

export function getApprovalResourceUrl(resourceType: string, resourceId: string | null): string | null {
    if (!resourceId) {
        return null
    }
    const config = APPROVAL_RESOURCE_CONFIG[resourceType]
    return config ? config.urlBuilder(resourceId) : null
}

export function getApprovalResourceLabel(resourceType: string): string {
    return APPROVAL_RESOURCE_CONFIG[resourceType]?.label || resourceType.replace(/_/g, ' ')
}

export type ApprovalResourceTypeValue = (typeof ApprovalResourceType)[keyof typeof ApprovalResourceType]

export interface ChangeRequestCreatedEventDetail {
    resourceType: ApprovalResourceTypeValue
    resourceId: string | number
}

export function dispatchChangeRequestCreated(detail: ChangeRequestCreatedEventDetail): void {
    window.dispatchEvent(
        new CustomEvent('change-request-created', {
            detail: {
                resourceType: detail.resourceType,
                resourceId: String(detail.resourceId),
            },
        })
    )
}

export function getApprovalResourceName(resourceType: string, intent: Record<string, any>): string | null {
    switch (resourceType) {
        case ApprovalResourceType.FEATURE_FLAG:
            return intent?.flag_key || null
        default:
            return null
    }
}
