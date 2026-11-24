import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { EvalFixProblemEnumApi } from '../../generated/api.schemas'
import { evaluationVolumeLogic } from '../evaluationVolumeLogic'
import type { LLMEvaluationLogicProps } from '../llmEvaluationLogic'
import { evaluationFixSuggestionLogic } from './evaluationFixSuggestionLogic'

export interface EvaluationFixSuggestionBannerProps {
    suggestionId: string
    evaluationLogicProps: LLMEvaluationLogicProps
    userAccessLevel: AccessControlLevel | undefined
    hasUnsavedChanges: boolean
}

export function EvaluationFixSuggestionBanner({
    suggestionId,
    evaluationLogicProps,
    userAccessLevel,
    hasUnsavedChanges,
}: EvaluationFixSuggestionBannerProps): JSX.Element | null {
    const logic = evaluationFixSuggestionLogic({ suggestionId, evaluationId: evaluationLogicProps.evaluationId })
    const { openFix, applying } = useValues(logic)
    const { applyFix } = useActions(logic)
    const { volume } = useValues(evaluationVolumeLogic(evaluationLogicProps))

    if (!openFix) {
        return null
    }
    const hasPatch = Object.keys(openFix.draft).length > 0
    // With nothing to apply, the form's live estimate already warns that no traffic matches.
    if (openFix.fix_problem === EvalFixProblemEnumApi.NoRuns && !hasPatch && volume?.matchingGenerations === 0) {
        return null
    }
    return (
        <LemonBanner
            type="warning"
            action={
                hasPatch
                    ? {
                          children: 'Apply change',
                          type: 'primary',
                          onClick: applyFix,
                          loading: applying,
                          // Applying reloads the form, which would drop the edits.
                          disabledReason: hasUnsavedChanges
                              ? 'Save or discard your changes first'
                              : getAccessControlDisabledReason(
                                    AccessControlResourceType.Evaluation,
                                    AccessControlLevel.Editor,
                                    userAccessLevel
                                ),
                          'data-attr': 'eval-suggestion-apply-fix',
                      }
                    : undefined
            }
        >
            <p className="m-0 font-semibold">{openFix.headline}</p>
            <p className="m-0">{openFix.outcome}</p>
        </LemonBanner>
    )
}
