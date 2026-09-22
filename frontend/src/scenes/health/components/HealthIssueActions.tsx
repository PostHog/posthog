import { IconEllipsis } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenu, LemonMenuItem } from 'lib/lemon-ui/LemonMenu'

import type { HealthIssue } from '../types'
import { SNOOZE_DURATIONS } from '../types'

export interface HealthIssueActionsProps {
    issue: HealthIssue
    onSnooze: (id: string, duration: string) => void
    onDismiss: (id: string) => void
    onUndismiss: (id: string) => void
}

export function HealthIssueActions({ issue, onSnooze, onDismiss, onUndismiss }: HealthIssueActionsProps): JSX.Element {
    // Snoozing something already hidden from the list has no visible effect, so a dismissed issue
    // only offers the way back.
    const items: LemonMenuItem[] = issue.dismissed
        ? [{ label: 'Undismiss', onClick: () => onUndismiss(issue.id) }]
        : [
              ...SNOOZE_DURATIONS.map(({ label, duration }) => ({
                  label,
                  onClick: () => onSnooze(issue.id, duration),
                  'data-attr': `health-issue-snooze-${duration}`,
              })),
              {
                  label: 'Dismiss',
                  onClick: () => onDismiss(issue.id),
                  'data-attr': 'health-issue-dismiss',
              },
          ]

    return (
        <LemonMenu items={items} placement="bottom-end">
            <LemonButton
                size="xsmall"
                type="tertiary"
                icon={<IconEllipsis />}
                tooltip="Snooze or dismiss"
                data-attr="health-issue-actions"
            />
        </LemonMenu>
    )
}
