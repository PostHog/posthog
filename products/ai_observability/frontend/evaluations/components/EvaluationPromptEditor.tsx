import { useActions, useValues } from 'kea'

import { LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { llmEvaluationLogic } from '../llmEvaluationLogic'

export function EvaluationPromptEditor(): JSX.Element {
    const { evaluation } = useValues(llmEvaluationLogic)
    const { setEvaluationPrompt } = useActions(llmEvaluationLogic)

    if (!evaluation || evaluation.evaluation_type !== 'llm_judge') {
        return <div>Loading...</div>
    }

    const prompt = evaluation.evaluation_config.prompt
    const allowsNA = evaluation.output_config.allows_na ?? false

    return (
        <div className="space-y-4">
            <LemonField.Pure label="Evaluation prompt">
                <div className="space-y-2">
                    <LemonTextArea
                        value={prompt}
                        onChange={setEvaluationPrompt}
                        placeholder={
                            evaluation.output_type === 'categorical'
                                ? 'Describe when each category applies.'
                                : evaluation.output_type === 'numeric'
                                  ? 'Describe how to score the response. Return a numeric score within the configured bounds.'
                                  : allowsNA
                                    ? `Write a prompt that evaluates the LLM generation and returns true, false, or N/A if the criteria doesn't apply.

Example: Is this response mathematically accurate? Return true if correct, false if incorrect, or N/A if no math is involved.`
                                    : `Write a prompt that evaluates the LLM generation and returns true or false.

Example: Is this response helpful and accurate? Return true if yes, false if no.`
                        }
                        rows={4}
                        className="font-mono text-sm"
                        maxLength={2000}
                    />
                </div>
            </LemonField.Pure>
        </div>
    )
}
