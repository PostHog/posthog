import { LemonBadge, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

export type IssueStatus = ErrorTrackingIssue['status']

export type Intent = 'data' | 'primary' | 'success' | 'warning' | 'danger' | 'muted' | undefined

export const sizeVariants = {
    xsmall: 'gap-1 text-xs',
    small: 'gap-2 text-sm',
    medium: 'gap-3 text-base',
    large: 'gap-3 text-lg',
}

interface LabelIndicatorProps {
    intent: Intent
    label: string
    size: 'xsmall' | 'small' | 'medium' | 'large'
    tooltip?: string
}

export function LabelIndicator({ intent, label, size, tooltip }: LabelIndicatorProps): JSX.Element {
    return (
        <Tooltip title={tooltip} placement="right">
            <div className={clsx('flex items-center', sizeVariants[size])}>
                <LemonBadge status={intent} size="small" />
                <div>{label}</div>
            </div>
        </Tooltip>
    )
}

export const STATUS_LABEL: Record<ErrorTrackingIssue['status'], string> = {
    active: 'Active',
    archived: 'Archived',
    resolved: 'Resolved',
    pending_release: 'Pending release',
    suppressed: 'Suppressed',
}

export const STATUS_INTENT: Record<ErrorTrackingIssue['status'], Intent> = {
    active: 'warning',
    archived: 'muted',
    resolved: 'success',
    pending_release: 'muted',
    suppressed: 'danger',
}

export const STATUS_TOOLTIP: Record<ErrorTrackingIssue['status'], string | undefined> = {
    suppressed: 'Stop capturing this issue',
    active: undefined,
    archived: undefined,
    resolved: undefined,
    pending_release: undefined,
}

interface StatusIndicatorProps {
    status: IssueStatus
    size?: 'xsmall' | 'small' | 'medium' | 'large'
    withTooltip?: boolean
}

export function StatusIndicator({ status, size = 'small', withTooltip }: StatusIndicatorProps): JSX.Element {
    return (
        <LabelIndicator
            intent={STATUS_INTENT[status]}
            size={size}
            label={STATUS_LABEL[status]}
            tooltip={withTooltip ? STATUS_TOOLTIP[status] : undefined}
        />
    )
}
