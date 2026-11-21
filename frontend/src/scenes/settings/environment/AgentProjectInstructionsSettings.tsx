import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { Button, Text } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { agentInstructionsSettingsLogic } from './agentInstructionsSettingsLogic'
import { InstructionsEditor } from './InstructionsEditor'
import { QuillInstructionsEditor } from './QuillInstructionsEditor'

export function AgentProjectInstructionsSettings(): JSX.Element {
    const { projectInstructions, projectValue, projectDirty, projectInstructionsLoading } =
        useValues(agentInstructionsSettingsLogic)
    const { setProjectDraft, submitProjectDraft } = useActions(agentInstructionsSettingsLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const Editor = todayRailNav ? QuillInstructionsEditor : InstructionsEditor
    const selfDrivingUrl = urls.settings('environment-self-driving', 'self-driving-steering')

    return (
        <div className="flex flex-col gap-2">
            <Editor
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
            {todayRailNav ? (
                <Button
                    className="self-start"
                    nativeButton={false}
                    render={<LinkPrimitive to={selfDrivingUrl} />}
                    data-attr="agent-project-instructions-self-driving"
                >
                    Customize Self-driving agents
                    <IconArrowRight aria-hidden />
                </Button>
            ) : (
                <LemonButton
                    className="self-start"
                    type="tertiary"
                    size="small"
                    to={selfDrivingUrl}
                    sideIcon={<IconArrowRight aria-hidden />}
                    data-attr="agent-project-instructions-self-driving"
                >
                    Customize Self-driving agents
                </LemonButton>
            )}
            {restrictionReason ? (
                todayRailNav ? (
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Only project admins can change these. You can still add your own instructions below.
                    </Text>
                ) : (
                    <p className="text-secondary mb-0">
                        Only project admins can change these. You can still add your own instructions below.
                    </p>
                )
            ) : null}
        </div>
    )
}
