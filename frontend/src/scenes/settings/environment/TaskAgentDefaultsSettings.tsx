import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { getEffortsForModel } from 'products/posthog_ai/frontend/utils/composerModels'

import { type AIRunPreferenceDraft, taskAgentDefaultsLogic } from './taskAgentDefaultsLogic'

// Mirrors the backend run-config registry (products/tasks/backend/temporal/process_task/utils.py);
// extend when new models ship. Codex models are offered here because the default also applies to
// surfaces that can run them (Slack, PostHog Code), even though the web tracker only drives Claude.
const MODEL_OPTIONS = [
    {
        title: 'Claude',
        options: [
            { value: 'claude-opus-4-8', label: 'Claude Opus 4.8' },
            { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6' },
        ],
    },
    {
        title: 'Codex',
        options: [
            { value: 'gpt-5.5', label: 'GPT-5.5' },
            { value: 'gpt-5', label: 'GPT-5' },
        ],
    },
]

function PreferenceEditor({
    draft,
    saving,
    inheritLabel,
    onChange,
    onSave,
}: {
    draft: AIRunPreferenceDraft
    saving: boolean
    inheritLabel: string
    onChange: (draft: Partial<AIRunPreferenceDraft>) => void
    onSave: () => void
}): JSX.Element {
    const effortOptions = getEffortsForModel(draft.model)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonSelect
                value={draft.model}
                onChange={(model) =>
                    onChange({
                        model,
                        // A model switch may invalidate the picked effort; reset to the server-side default.
                        reasoning_effort:
                            draft.reasoning_effort &&
                            model &&
                            getEffortsForModel(model).some((option) => option.value === draft.reasoning_effort)
                                ? draft.reasoning_effort
                                : null,
                    })
                }
                options={[{ options: [{ value: null as string | null, label: inheritLabel }] }, ...MODEL_OPTIONS]}
                placeholder={inheritLabel}
                data-attr="task-agent-default-model"
            />
            <LemonSelect
                value={draft.reasoning_effort}
                onChange={(reasoning_effort) => onChange({ reasoning_effort })}
                options={[
                    { value: null as string | null, label: 'Default effort' },
                    ...effortOptions.map(({ value, label }) => ({ value: value as string, label })),
                ]}
                disabledReason={draft.model ? undefined : 'Pick a model first'}
                data-attr="task-agent-default-effort"
            />
            <LemonButton type="primary" onClick={onSave} loading={saving}>
                Save
            </LemonButton>
        </div>
    )
}

export function TaskAgentProjectDefaultSettings(): JSX.Element {
    const { teamDraft, teamPreferencesLoading } = useValues(taskAgentDefaultsLogic)
    const { setTeamDraft, submitTeamDraft } = useActions(taskAgentDefaultsLogic)

    return (
        <PreferenceEditor
            draft={teamDraft}
            saving={teamPreferencesLoading}
            inheritLabel="No project default"
            onChange={setTeamDraft}
            onSave={submitTeamDraft}
        />
    )
}

export function TaskAgentMyPreferenceSettings(): JSX.Element {
    const { myDraft, myConfigLoading, resolvedDefaults } = useValues(taskAgentDefaultsLogic)
    const { setMyDraft, submitMyDraft } = useActions(taskAgentDefaultsLogic)

    return (
        <div className="flex flex-col gap-2">
            <PreferenceEditor
                draft={myDraft}
                saving={myConfigLoading}
                inheritLabel="Use project default"
                onChange={setMyDraft}
                onSave={submitMyDraft}
            />
            <p className="text-secondary mb-0">
                {resolvedDefaults?.model ? (
                    <>
                        Runs you start without picking a model will use <strong>{resolvedDefaults.model}</strong>
                        {resolvedDefaults.reasoning_effort ? (
                            <> ({resolvedDefaults.reasoning_effort} effort)</>
                        ) : null}{' '}
                        from the {resolvedDefaults.source === 'user' ? 'preference above' : 'project default'}.
                    </>
                ) : (
                    <>No default is set — runs use each surface's built-in model.</>
                )}
            </p>
        </div>
    )
}
