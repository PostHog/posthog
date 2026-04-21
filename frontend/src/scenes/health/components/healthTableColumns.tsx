import { IconRevert, IconX } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'

import { severityToTagType } from '../healthUtils'
import type { HealthIssue } from '../types'
import { SEVERITY_ORDER } from '../types'

export function severityColumn(): LemonTableColumn<HealthIssue, keyof HealthIssue | undefined> {
    return {
        title: 'Severity',
        key: 'severity',
        width: 100,
        render: function Render(_, issue: HealthIssue) {
            return (
                <LemonTag type={severityToTagType(issue.severity)} size="small">
                    {issue.severity}
                </LemonTag>
            )
        },
        sorter: (a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity),
    }
}

export function dismissActionColumn(
    onDismiss: (id: string) => void,
    onUndismiss: (id: string) => void
): LemonTableColumn<HealthIssue, keyof HealthIssue | undefined> {
    return {
        key: 'actions',
        width: 40,
        render: function Render(_, issue: HealthIssue) {
            return (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={issue.dismissed ? <IconRevert /> : <IconX />}
                    tooltip={issue.dismissed ? 'Undismiss' : 'Dismiss'}
                    onClick={() => (issue.dismissed ? onUndismiss(issue.id) : onDismiss(issue.id))}
                />
            )
        },
    }
}
