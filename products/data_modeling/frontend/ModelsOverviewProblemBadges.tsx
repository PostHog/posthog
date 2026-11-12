import { IconClock, IconPauseFilled, IconWarning, IconXCircle } from '@posthog/icons'
import { Badge, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { IssueKind, IssueStatus, IssueTone } from './overviewIssueCopy'

const BADGE_VARIANTS: Record<IssueTone, 'destructive' | 'warning'> = {
    danger: 'destructive',
    warning: 'warning',
}

const ISSUE_ICONS: Record<IssueKind, typeof IconClock> = {
    suspended: IconPauseFilled,
    failed: IconXCircle,
    behind: IconClock,
    checks: IconWarning,
}

export function ModelsOverviewProblemBadges({ statuses }: { statuses: IssueStatus[] }): JSX.Element {
    return (
        <div className="flex flex-wrap gap-1">
            {statuses.map(({ kind, label, tone, tooltip }) => {
                const Icon = ISSUE_ICONS[kind]
                return (
                    <Tooltip key={kind}>
                        <TooltipTrigger delay={0} render={<span className="inline-flex" />}>
                            <Badge variant={BADGE_VARIANTS[tone]}>
                                <Icon aria-hidden />
                                {label}
                            </Badge>
                        </TooltipTrigger>
                        <TooltipContent>{tooltip}</TooltipContent>
                    </Tooltip>
                )
            })}
        </div>
    )
}
