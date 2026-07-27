import { IconRevert, IconSparkles, IconX } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { buildHealthIssuePrompt, severityToTagType } from '../healthUtils'
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
    // LemonTable invokes a column's render as a plain function, not a component, so we can't use hooks
    // (useValues/useActions) inside it — read the flag and dispatch the action via the singleton logics directly.
    // This re-evaluates whenever the table re-renders (the Health scene reads the flag reactively above it).
    const askAiEnabled = !!featureFlagLogic.findMounted()?.values.featureFlags?.[FEATURE_FLAGS.HEALTH_ASK_AI]
    return {
        key: 'actions',
        width: 80,
        render: function Render(_, issue: HealthIssue) {
            return (
                <div className="flex items-center gap-1">
                    {askAiEnabled && (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={<IconSparkles />}
                            tooltip="Ask PostHog AI about this issue"
                            onClick={() =>
                                sidePanelStateLogic.actions.openSidePanel(
                                    SidePanelTab.Max,
                                    `!${buildHealthIssuePrompt(issue)}`
                                )
                            }
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
            )
        },
    }
}
