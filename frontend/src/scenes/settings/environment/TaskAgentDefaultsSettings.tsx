import { useActions, useValues } from 'kea'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { modelCatalogueLogic } from 'products/posthog_ai/frontend/logics/modelCatalogueLogic'
import { getEffortLabel, getModelLabel } from 'products/posthog_ai/frontend/utils/composerModels'
import { AIRunPreferenceEditor } from 'products/tasks/frontend/components/AIRunPreferenceEditor'

import { taskAgentDefaultsLogic } from './taskAgentDefaultsLogic'

export function TaskAgentProjectDefaultSettings(): JSX.Element {
    const { teamDraft, teamDraftDirty, teamPreferencesLoading } = useValues(taskAgentDefaultsLogic)
    const { setTeamDraft, submitTeamDraft } = useActions(taskAgentDefaultsLogic)
    // This one default applies to everyone on the project, so it's admin-only — unlike the personal
    // preference below, which each person owns.
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <div className="flex flex-col gap-2">
            <AIRunPreferenceEditor
                draft={teamDraft}
                dirty={teamDraftDirty}
                saving={teamPreferencesLoading}
                inheritLabel="No project default"
                onChange={setTeamDraft}
                onSave={submitTeamDraft}
                restrictionReason={restrictionReason}
            />
            {restrictionReason ? (
                <p className="text-secondary mb-0">
                    Only project admins can change this. You can still set your own default below.
                </p>
            ) : null}
        </div>
    )
}

export function TaskAgentMyPreferenceSettings(): JSX.Element {
    const { myDraft, myDraftDirty, myPreferencesLoading, canResetMyPreference, resolvedDefaults } =
        useValues(taskAgentDefaultsLogic)
    const { catalogue } = useValues(modelCatalogueLogic)
    const { setMyDraft, submitMyDraft, resetMyPreference } = useActions(taskAgentDefaultsLogic)

    return (
        <div className="flex flex-col gap-2">
            <AIRunPreferenceEditor
                draft={myDraft}
                dirty={myDraftDirty}
                saving={myPreferencesLoading}
                inheritLabel="Use project default"
                onChange={setMyDraft}
                onSave={submitMyDraft}
                onReset={resetMyPreference}
                canReset={canResetMyPreference}
            />
            <p className="text-secondary mb-0">
                {resolvedDefaults?.model ? (
                    <>
                        Runs you start without picking a model will use{' '}
                        <strong>{getModelLabel(catalogue, resolvedDefaults.model)}</strong>
                        {resolvedDefaults.reasoning_effort ? (
                            <> ({getEffortLabel(resolvedDefaults.reasoning_effort)} effort)</>
                        ) : null}{' '}
                        from {resolvedDefaults.source === 'user' ? 'your default above' : 'the project default'}.
                    </>
                ) : (
                    <>No default is set. Runs use each surface's built-in model.</>
                )}
            </p>
        </div>
    )
}
