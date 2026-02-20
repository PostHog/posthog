import { useActions } from 'kea'

import { IconRevert, IconX } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { healthSceneLogic } from '../healthSceneLogic'
import { kindToLabel, severityLabel, severityToTagType } from '../healthUtils'
import { getIssueRenderer } from '../issueRenderers'
import type { HealthIssue } from '../types'

export const HealthIssueCard = ({ issue }: { issue: HealthIssue }): JSX.Element => {
    const { dismissIssue, undismissIssue } = useActions(healthSceneLogic)
    const Renderer = getIssueRenderer(issue.kind)

    return (
        <div className="px-4 py-3 bg-surface-primary">
            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                    <span className="text-sm font-medium">{kindToLabel(issue.kind)}</span>
                    <LemonTag type={severityToTagType(issue.severity)} size="small" className="shrink-0">
                        {severityLabel(issue.severity)}
                    </LemonTag>
                    <span className="text-xs text-muted shrink-0">
                        <TZLabel time={issue.created_at} />
                    </span>
                </div>
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={issue.dismissed ? <IconRevert /> : <IconX />}
                    tooltip={issue.dismissed ? 'Undismiss' : 'Dismiss'}
                    onClick={() => (issue.dismissed ? undismissIssue(issue.id) : dismissIssue(issue.id))}
                />
            </div>
            <Renderer issue={issue} />
        </div>
    )
}
