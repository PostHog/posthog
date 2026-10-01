import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton, LemonTextArea } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { agentInstructionsSettingsLogic } from './agentInstructionsSettingsLogic'

// Matches AGENT_INSTRUCTIONS_MAX_LENGTH on the backend, which rejects anything longer.
const MAX_LENGTH = 20_000

function InstructionsEditor({
    stored,
    value,
    dirty,
    loading,
    placeholder,
    onChange,
    onSave,
    restrictionReason,
    dataAttr,
}: {
    stored: string | null
    value: string
    dirty: boolean
    loading: boolean
    placeholder: string
    onChange: (value: string) => void
    onSave: () => void
    restrictionReason?: string | null
    dataAttr: string
}): JSX.Element {
    if (stored === null) {
        return loading ? (
            <LemonSkeleton className="h-32 w-full" />
        ) : (
            <p className="text-danger mb-0">Couldn't load these instructions. Refresh the page to try again.</p>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonTextArea
                value={value}
                onChange={onChange}
                placeholder={placeholder}
                minRows={6}
                maxRows={24}
                maxLength={MAX_LENGTH}
                disabled={!!restrictionReason || loading}
                data-attr={`${dataAttr}-input`}
            />
            <div className="flex flex-wrap gap-2">
                <LemonButton
                    type="primary"
                    onClick={onSave}
                    loading={loading}
                    disabledReason={restrictionReason ?? (dirty ? undefined : 'No changes to save')}
                    data-attr={`${dataAttr}-save`}
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}

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
            />
            {restrictionReason ? (
                <p className="text-secondary mb-0">
                    Only project admins can change these. You can still add your own instructions below.
                </p>
            ) : null}
        </div>
    )
}

export function AgentPersonalInstructionsSettings(): JSX.Element {
    const { personalInstructions, personalValue, personalDirty, personalInstructionsLoading } =
        useValues(agentInstructionsSettingsLogic)
    const { setPersonalDraft, submitPersonalDraft } = useActions(agentInstructionsSettingsLogic)

    return (
        <InstructionsEditor
            stored={personalInstructions}
            value={personalValue}
            dirty={personalDirty}
            loading={personalInstructionsLoading}
            placeholder="For example: Keep pull request descriptions short. Ask before adding a dependency."
            onChange={setPersonalDraft}
            onSave={submitPersonalDraft}
            dataAttr="agent-personal-instructions"
        />
    )
}
