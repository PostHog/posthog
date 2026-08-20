import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { modelCatalogueLogic } from 'products/posthog_ai/frontend/logics/modelCatalogueLogic'
import {
    filterEffortForModel,
    getEffortLabel,
    getEffortsForModel,
    getModelLabel,
    getRuntimeAdapterLabel,
    listRuntimeAdapters,
    modelsForRuntimeAdapter,
} from 'products/posthog_ai/frontend/utils/composerModels'

import { type AIRunPreferenceDraft, taskAgentDefaultsLogic } from './taskAgentDefaultsLogic'

function PreferenceEditor({
    draft,
    dirty,
    saving,
    inheritLabel,
    onChange,
    onSave,
    onReset,
    canReset,
    restrictionReason,
}: {
    draft: AIRunPreferenceDraft
    dirty: boolean
    saving: boolean
    inheritLabel: string
    onChange: (draft: Partial<AIRunPreferenceDraft>) => void
    onSave: () => void
    onReset?: () => void
    canReset?: boolean
    /** Set when the viewer may not edit this level, which disables every control here. */
    restrictionReason?: string | null
}): JSX.Element {
    const { catalogue } = useValues(modelCatalogueLogic)

    // Grouped by harness off the same catalogue the composer renders, so a model you can pick for a
    // run is always settable as a default and vice versa — including the Codex models that only
    // Slack and PostHog Desktop drive today.
    const modelOptions = useMemo(
        () =>
            listRuntimeAdapters(catalogue).map((adapter) => ({
                title: getRuntimeAdapterLabel(adapter),
                options: modelsForRuntimeAdapter(catalogue, adapter).map((choice) => ({
                    value: choice.model,
                    label: choice.display_name,
                })),
            })),
        [catalogue]
    )
    const effortOptions = useMemo(() => getEffortsForModel(catalogue, draft.model), [catalogue, draft.model])

    return (
        <div className="flex flex-wrap items-end gap-2">
            <LemonField.Pure label="Model" className="min-w-60">
                <LemonSelect
                    fullWidth
                    value={draft.model}
                    onChange={(model) =>
                        onChange({
                            model,
                            // A model switch may invalidate the picked effort; drop it rather than store one
                            // the model can't run, and let the server-side default apply instead.
                            reasoning_effort:
                                draft.reasoning_effort && model
                                    ? filterEffortForModel(catalogue, draft.reasoning_effort, model)
                                    : null,
                        })
                    }
                    options={[{ options: [{ value: null as string | null, label: inheritLabel }] }, ...modelOptions]}
                    placeholder={inheritLabel}
                    disabledReason={restrictionReason ?? (saving ? 'Saving…' : undefined)}
                    data-attr="task-agent-default-model"
                />
            </LemonField.Pure>
            <LemonField.Pure label="Reasoning effort" className="min-w-48">
                <LemonSelect
                    fullWidth
                    value={draft.reasoning_effort}
                    onChange={(reasoning_effort) => onChange({ reasoning_effort })}
                    options={[
                        { value: null as string | null, label: 'Default effort' },
                        ...effortOptions.map(({ value, label }) => ({ value: value as string, label })),
                    ]}
                    disabledReason={
                        restrictionReason ?? (saving ? 'Saving…' : draft.model ? undefined : 'Pick a model first')
                    }
                    data-attr="task-agent-default-effort"
                />
            </LemonField.Pure>
            <LemonButton
                type="primary"
                onClick={onSave}
                loading={saving}
                disabledReason={restrictionReason ?? (dirty ? undefined : 'No changes to save')}
            >
                Save
            </LemonButton>
            {onReset && (
                <LemonButton
                    type="secondary"
                    onClick={onReset}
                    loading={saving}
                    disabledReason={canReset ? undefined : 'Already using the project default'}
                >
                    Reset to project default
                </LemonButton>
            )}
        </div>
    )
}

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
            <PreferenceEditor
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
            <PreferenceEditor
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
                    <>No default is set — runs use each surface's built-in model.</>
                )}
            </p>
        </div>
    )
}
