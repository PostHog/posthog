import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { modelPickerLogic } from '../../modelPickerLogic'
import { AddKeyModal } from '../../settings/AddKeyModal'
import { llmProviderKeysLogic } from '../../settings/llmProviderKeysLogic'

/** Lets a team without an AI provider key add one in place, so the evaluation it is setting up stays as it is. */
export function EvaluationProviderKeyBanner(): JSX.Element | null {
    const { evaluationModelNotice } = useValues(modelPickerLogic)
    const { setNewKeyModalOpen } = useActions(llmProviderKeysLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    if (evaluationModelNotice?.kind !== 'no-keys') {
        return null
    }
    return (
        <>
            <LemonBanner
                type="info"
                action={{
                    children: 'Add API key',
                    onClick: () => setNewKeyModalOpen(true),
                    disabledReason: restrictionReason,
                    'data-attr': 'llma-evaluation-add-provider-key',
                }}
            >
                {restrictionReason
                    ? 'This project has no AI provider key yet. Ask a project admin to add one, such as an OpenAI or Anthropic key.'
                    : 'This project has no AI provider key yet. Add one, such as an OpenAI or Anthropic key, to pick the model that judges each run.'}
            </LemonBanner>
            <AddKeyModal restrictionReason={restrictionReason} />
        </>
    )
}
