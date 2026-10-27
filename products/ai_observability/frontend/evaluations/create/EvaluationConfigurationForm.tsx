import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { EvaluationCodeEditor } from '../components/EvaluationCodeEditor'
import { EvaluationPromptEditor } from '../components/EvaluationPromptEditor'
import { evaluationVolumeLogic } from '../evaluationVolumeLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationNameFields } from './EvaluationNameFields'
import { EvaluationOutputFields } from './EvaluationOutputFields'
import { EvaluationSentence } from './EvaluationSentence'

/** A saved evaluation's settings, laid out like the new evaluation page: name, one sentence, then the instructions. */
export function EvaluationConfigurationForm(): JSX.Element | null {
    const { evaluation, canEnable, canEnableReason } = useValues(llmEvaluationLogic)
    const { setEvaluationEnabled } = useActions(llmEvaluationLogic)
    const { props } = useMountedLogic(llmEvaluationLogic)

    if (!evaluation) {
        return null
    }
    return (
        <BindLogic logic={evaluationVolumeLogic} props={props}>
            <div className="bg-bg-light border rounded p-4 @min-[40rem]/evaluation:p-6 flex flex-col gap-6">
                <EvaluationNameFields />
                <EvaluationSentence />
                <div className="flex flex-col gap-4 min-w-0">
                    {evaluation.evaluation_type === 'llm_judge' && <EvaluationPromptEditor />}
                    {evaluation.evaluation_type === 'hog' && <EvaluationCodeEditor />}
                    <EvaluationOutputFields />
                </div>
                <LemonSwitch
                    checked={evaluation.enabled}
                    onChange={setEvaluationEnabled}
                    disabledReason={!canEnable && !evaluation.enabled ? (canEnableReason ?? undefined) : undefined}
                    label={evaluation.enabled ? 'Running on new traffic' : 'Paused'}
                    bordered
                    data-attr="llma-evaluation-configuration-enabled"
                />
            </div>
        </BindLogic>
    )
}
