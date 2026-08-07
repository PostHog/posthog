import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronRight, IconRevert, IconSparkles, IconX } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { CATEGORY_DETAIL_CONFIG } from '../categoryDetail/categoryDetailConfig'
import { categoryForKind } from '../healthCategories'
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

    const category = categoryForKind(issue.kind)
    const detailUrl = CATEGORY_DETAIL_CONFIG[category]?.redirectUrl ?? urls.healthCategory(category)

    const askMax = (): void => openSidePanel(SidePanelTab.Max, `!${buildHealthIssuePrompt(issue)}`)
    const openDetail = (): void => router.actions.push(detailUrl)

    // The card is a click target for the category drill-down. Inner buttons and any links the
    // renderer draws stop propagation so they keep their own behavior.
    return (
        <div
            className="group px-4 py-3 bg-surface-primary cursor-pointer transition-colors hover:bg-fill-button-tertiary-hover"
            role="link"
            tabIndex={0}
            onClick={openDetail}
            onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    openDetail()
                }
            }}
        >
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
                            onClick={(e) => {
                                e.stopPropagation()
                                askMax()
                            }}
                        />
                    )}
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        icon={issue.dismissed ? <IconRevert /> : <IconX />}
                        tooltip={issue.dismissed ? 'Undismiss' : 'Dismiss'}
                        onClick={(e) => {
                            e.stopPropagation()
                            issue.dismissed ? onUndismiss(issue.id) : onDismiss(issue.id)
                        }}
                    />
                    <IconChevronRight className="size-4 text-muted opacity-0 group-hover:opacity-100 transition-opacity" />
                </div>
            </div>
            <Renderer issue={issue} />
        </div>
    )
}
