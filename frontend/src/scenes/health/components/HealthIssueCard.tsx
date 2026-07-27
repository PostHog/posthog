import { useActions, useValues } from 'kea'

import { IconRevert, IconSparkles, IconX } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { buildHealthIssuePrompt, kindToLabel, severityLabel, severityToTagType } from '../healthUtils'
import { getIssueRenderer } from '../issueRenderers'
import type { HealthIssue } from '../types'

export const HealthIssueCard = ({
    issue,
    onDismiss,
    onUndismiss,
}: {
    issue: HealthIssue
    onDismiss: (id: string) => void
    onUndismiss: (id: string) => void
}): JSX.Element => {
    const Renderer = getIssueRenderer(issue.kind)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const askAiEnabled = !!featureFlags[FEATURE_FLAGS.HEALTH_ASK_AI]

    const askMax = (): void => openSidePanel(SidePanelTab.Max, `!${buildHealthIssuePrompt(issue)}`)

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
                <div className="flex items-center gap-1 shrink-0">
                    {askAiEnabled && (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={<IconSparkles />}
                            tooltip="Ask PostHog AI about this issue"
                            onClick={askMax}
                        />
                    )}
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        icon={issue.dismissed ? <IconRevert /> : <IconX />}
                        tooltip={issue.dismissed ? 'Undismiss' : 'Dismiss'}
                        onClick={() => (issue.dismissed ? onUndismiss(issue.id) : onDismiss(issue.id))}
                    />
                </div>
            </div>
            <Renderer issue={issue} />
        </div>
    )
}
