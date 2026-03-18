import type { LemonTagType } from '@posthog/lemon-ui'

import { KIND_LABELS } from './healthCategories'
import type { HealthIssueSeverity } from './types'

export const severityToTagType = (severity: HealthIssueSeverity): LemonTagType => {
    switch (severity) {
        case 'critical':
            return 'danger'
        case 'warning':
            return 'warning'
        case 'info':
            return 'completion'
    }
}

export const severityLabel = (severity: HealthIssueSeverity): string => {
    return severity.charAt(0).toUpperCase() + severity.slice(1)
}

export const kindToLabel = (kind: string): string => {
    if (KIND_LABELS[kind]) {
        return KIND_LABELS[kind]
    }
    return kind
        .split('_')
        .map((word, i) => (i === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word))
        .join(' ')
}
