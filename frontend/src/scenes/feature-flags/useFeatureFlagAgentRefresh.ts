import { useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'

import { FEATURE_FLAG_MUTATION_TOOLS, mutationTargetsFeatureFlag } from './featureFlagAiContext'

export interface UseFeatureFlagAgentRefreshOptions {
    /** The saved flag on screen, or null while it is unsaved or unloaded. */
    flagId: number | null
    onAgentChange: () => void
}

// Every matching completion is checked rather than only the turn's last one: a turn that changes
// this flag and then another one would otherwise leave this page stale.
export function useFeatureFlagAgentRefresh({ flagId, onAgentChange }: UseFeatureFlagAgentRefreshOptions): void {
    useMcpToolApplyBack({
        tools: FEATURE_FLAG_MUTATION_TOOLS,
        targetKey: `feature_flag:${flagId ?? 'unloaded'}`,
        active: flagId !== null,
        applyOn: 'tool_call_completed',
        onApply: (_event, { innerInput }) => {
            if (flagId !== null && mutationTargetsFeatureFlag(innerInput, flagId)) {
                onAgentChange()
            }
        },
    })
}
