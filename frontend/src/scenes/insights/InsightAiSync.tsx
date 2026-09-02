import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { InsightLogicProps } from '~/types'

import { useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'

import { INSIGHT_AI_TOOL_NAMES, insightAiSyncLogic } from './insightAiSyncLogic'
import { insightLogic } from './insightLogic'

export function InsightAiSync({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element | null {
    const { insight } = useValues(insightLogic(insightLogicProps))
    const logic = insightAiSyncLogic({ insightLogicProps })
    const { hasPendingAiConflict } = useValues(logic)
    const { agentToolCompleted, keepMyChanges, useAiChanges } = useActions(logic)

    useMcpToolApplyBack({
        tools: [...INSIGHT_AI_TOOL_NAMES],
        targetKey: 'insight:' + (insight.short_id ?? 'unloaded'),
        active: !!insight.saved && !!insight.short_id,
        applyOn: 'tool_call_completed',
        onApply: (event, { innerInput }) => agentToolCompleted(event.toolName, innerInput),
    })

    if (!hasPendingAiConflict) {
        return null
    }

    return (
        <LemonBanner type="warning">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                    <strong>PostHog AI updated this insight</strong>
                    <p className="mb-0">
                        You have unsaved changes. Keep editing your version, or load the AI version and discard your
                        changes. Saving your version will replace the AI update.
                    </p>
                </div>
                <div className="flex flex-wrap gap-2">
                    <LemonButton type="secondary" size="small" onClick={keepMyChanges}>
                        Keep my changes
                    </LemonButton>
                    <LemonButton type="primary" size="small" onClick={useAiChanges}>
                        Use AI changes
                    </LemonButton>
                </div>
            </div>
        </LemonBanner>
    )
}
