import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, Tooltip } from '@posthog/lemon-ui'

import { EvaluationJudgeModelPicker } from '../components/EvaluationJudgeModelPicker'
import { decisionModelHint } from '../constants'
import { llmEvaluationLogic } from '../llmEvaluationLogic'

/** The model a judge or decision model runs on, from the team's AI providers, with what that model does. */
export function EvaluationModelPanel(): JSX.Element | null {
    const { evaluation, usesDecisionModel, includeMedia } = useValues(llmEvaluationLogic)
    const { setIncludeMedia } = useActions(llmEvaluationLogic)

    if (!evaluation) {
        return null
    }
    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-start gap-x-6 gap-y-2">
                <div className="w-80 max-w-full">
                    <EvaluationJudgeModelPicker />
                </div>
                <p className="mb-0 flex-1 basis-64 text-sm text-secondary">
                    {usesDecisionModel
                        ? decisionModelHint(evaluation.output_type)
                        : 'Runs on your own AI provider key. Each run is one call to this model.'}
                </p>
            </div>
            {!usesDecisionModel && (
                <div className="flex flex-col gap-0.5">
                    <div className="flex items-center gap-1">
                        <LemonCheckbox
                            checked={includeMedia}
                            onChange={setIncludeMedia}
                            label="Send attachments to the judge"
                            data-attr="llma-evaluation-include-attachments"
                        />
                        <Tooltip
                            title="PDFs need an OpenAI, Anthropic, or Gemini model, audio a Gemini or OpenAI audio model, and video a Gemini model. On OpenRouter, the judge gets the file types its model reads. It judges the text alone when its model can't read a file, past 20 attachments, or when the provider rejects a file."
                            openOnClick
                        >
                            <IconInfo className="text-secondary text-base" aria-label="Which models read which files" />
                        </Tooltip>
                    </div>
                    <span className="text-xs text-secondary pl-6">
                        For checks that depend on images, PDFs, audio, or video. Each file adds input tokens, so runs
                        cost more.
                    </span>
                </div>
            )}
        </div>
    )
}
