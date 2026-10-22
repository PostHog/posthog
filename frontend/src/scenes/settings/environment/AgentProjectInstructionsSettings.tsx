import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { urls } from 'scenes/urls'

import { agentInstructionsSettingsLogic } from './agentInstructionsSettingsLogic'
import { InstructionsEditor } from './InstructionsEditor'

export function AgentProjectInstructionsSettings(): JSX.Element {
    const { projectInstructions, projectValue, projectDirty, projectInstructionsLoading } =
        useValues(agentInstructionsSettingsLogic)
    const { setProjectDraft, submitProjectDraft } = useActions(agentInstructionsSettingsLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <div className="flex flex-col gap-2">
            <InstructionsEditor
                stored={projectInstructions}
                value={projectValue}
                dirty={projectDirty}
                loading={projectInstructionsLoading}
                placeholder="For example: Use pnpm, not npm. Open pull requests as drafts."
                onChange={setProjectDraft}
                onSave={submitProjectDraft}
                restrictionReason={restrictionReason}
                dataAttr="agent-project-instructions"
                ariaLabel="Project instructions"
            />
            <LemonButton
                className="self-start"
                type="tertiary"
                size="small"
                to={`${urls.inbox('settings')}#steering`}
                sideIcon={<IconArrowRight aria-hidden />}
                data-attr="agent-project-instructions-self-driving"
            >
                Customize Self-driving agents
            </LemonButton>
            {restrictionReason ? (
                <p className="text-secondary mb-0">
                    Only project admins can change these. You can still add your own instructions below.
                </p>
            ) : null}
        </div>
    )
}
