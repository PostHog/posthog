import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { evaluationFixSuggestionLogic } from './evaluationFixSuggestionLogic'

export interface EvaluationFixSuggestionBannerProps {
    suggestionId: string
    evaluationId: string
    userAccessLevel: AccessControlLevel | undefined
    hasUnsavedChanges: boolean
}

export function EvaluationFixSuggestionBanner({
    suggestionId,
    evaluationId,
    userAccessLevel,
    hasUnsavedChanges,
}: EvaluationFixSuggestionBannerProps): JSX.Element | null {
    const logic = evaluationFixSuggestionLogic({ suggestionId, evaluationId })
    const { openFix, applying } = useValues(logic)
    const { applyFix } = useActions(logic)

    if (!openFix) {
        return null
    }
    const hasPatch = Object.keys(openFix.draft).length > 0
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
