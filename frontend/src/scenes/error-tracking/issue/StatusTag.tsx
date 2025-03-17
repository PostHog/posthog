import clsx from 'clsx'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

export type IssueStatus = ErrorTrackingIssue['status']

export const STATUS_LABEL: Record<ErrorTrackingIssue['status'], string> = {
    active: 'Active',
    archived: 'Archived',
    resolved: 'Resolved',
    pending_release: 'Pending release',
    suppressed: 'Suppressed',
}

export const STATUS_INTENT: Record<ErrorTrackingIssue['status'], Intent> = {
    active: 'yellow',
    archived: 'key',
    resolved: 'blue',
    pending_release: 'key',
    suppressed: 'red',
}

export type Intent = 'yellow' | 'blue' | 'red' | 'key'

export const INTENT_CLASS: Record<Intent, string> = {
    yellow: 'bg-brand-yellow',
    blue: 'bg-brand-blue',
    key: 'bg-brand-key',
    red: 'bg-brand-red',
}

export function IndicatorTag({
    intent,
    label,
    size,
}: {
    intent: 'blue' | 'yellow' | 'red' | 'key'
    label: string
    size: 'xsmall' | 'small' | 'medium' | 'large'
}): JSX.Element {
    return (
        <div
            className={clsx('flex items-center', {
                'gap-1': size === 'xsmall',
                'gap-2': size === 'small',
                'gap-3': size === 'medium' || size === 'large',
            })}
        >
            <div className={clsx(INTENT_CLASS[intent], 'h-2 w-2 rounded-full')} />
            <div
                className={clsx({
                    'text-xs': size === 'xsmall',
                    'text-sm': size === 'small',
                    'text-base': size === 'medium',
                    'text-lg': size === 'large',
                })}
            >
                {label}
            </div>
        </div>
    )
}

export function StatusTag({
    status,
    label,
    size = 'small',
}: {
    status: IssueStatus
    label?: string
    size?: 'xsmall' | 'small' | 'medium' | 'large'
}): JSX.Element {
    return <IndicatorTag intent={STATUS_INTENT[status]} size={size} label={label || STATUS_LABEL[status]} />
}
