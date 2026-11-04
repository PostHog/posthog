import { IconClock, IconPauseFilled, IconWarning, IconXCircle } from '@posthog/icons'
import { Badge, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { AttentionSubject } from './modelsOverviewLogic'
import { IssueKind, IssueStatus, IssueTone, failingChecksStatus, materializationStatus } from './overviewIssueCopy'

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

function subjectStatuses(subject: AttentionSubject): IssueStatus[] {
    return [
        ...(subject.materialization ? [materializationStatus(subject.materialization)] : []),
        ...(subject.failingChecks.length > 0 ? [failingChecksStatus(subject.failingChecks)] : []),
    ]
}

export interface ModelsOverviewProblemBadgesProps {
    subject: AttentionSubject
    checksHref?: string | null
}

export function ModelsOverviewProblemBadges({ subject, checksHref }: ModelsOverviewProblemBadgesProps): JSX.Element {
    return (
        <div className="flex flex-wrap gap-1">
            {subjectStatuses(subject).map(({ kind, label, tone, tooltip }) => {
                const Icon = ISSUE_ICONS[kind]
                const href = kind === 'checks' ? checksHref : null
                return (
                    <Tooltip key={kind}>
                        <TooltipTrigger
                            delay={0}
                            render={
                                href ? (
                                    <LinkPrimitive
                                        to={href}
                                        className="inline-flex"
                                        data-attr="models-list-checks-badge"
                                    />
                                ) : (
                                    <span className="inline-flex" />
                                )
                            }
                        >
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
