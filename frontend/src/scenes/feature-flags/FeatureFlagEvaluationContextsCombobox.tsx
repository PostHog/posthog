import { useValues } from 'kea'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'

import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'

import { defaultEvaluationContextsLogic } from './defaultEvaluationContextsLogic'

type FeatureFlagEvaluationContextsComboboxProps = {
    evaluationContexts: string[]
    onSave: (evaluationContexts: string[]) => void
    disabledReason?: string | null
}

export function FeatureFlagEvaluationContextsCombobox({
    evaluationContexts,
    onSave,
    disabledReason,
}: FeatureFlagEvaluationContextsComboboxProps): JSX.Element {
    const { availableContexts, defaultEvaluationContextsLoading } = useValues(defaultEvaluationContextsLogic)

    return (
        <ScenePanelLabel title="Evaluation contexts">
            <TagsCombobox
                value={evaluationContexts}
                onChange={onSave}
                loading={defaultEvaluationContextsLoading}
                options={availableContexts.filter((context) => !evaluationContexts.includes(context))}
                placeholder="Add contexts..."
                disabled={!!disabledReason}
                allowCustomValues
                customValueNoun="context"
                dataAttr="feature_flag-evaluation-contexts-input"
            />
            {disabledReason ? <span className="text-xs text-tertiary mt-1">{disabledReason}</span> : null}
        </ScenePanelLabel>
    )
}
