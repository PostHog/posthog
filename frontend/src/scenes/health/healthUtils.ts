import type { LemonTagType } from '@posthog/lemon-ui'

import { KIND_LABELS } from './healthCategories'
import type { HealthIssueKind } from './healthCategories'
import type { HealthIssue, HealthIssueSeverity } from './types'
import { SEVERITY_ORDER } from './types'

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

export const worstSeverity = (issues: HealthIssue[]): HealthIssueSeverity => {
    for (const severity of SEVERITY_ORDER) {
        if (issues.some((i) => i.severity === severity)) {
            return severity
        }
    }
    return 'info'
}

export const severityColor = (severity: HealthIssueSeverity): string => {
    switch (severity) {
        case 'critical':
            return 'text-danger'
        case 'warning':
            return 'text-warning'
        case 'info':
            return 'text-muted'
    }
}

export const kindToLabel = (kind: string): string => {
    if (kind in KIND_LABELS) {
        return KIND_LABELS[kind as HealthIssueKind]
    }
    return kind
        .split('_')
        .map((word, i) => (i === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word))
        .join(' ')
}
