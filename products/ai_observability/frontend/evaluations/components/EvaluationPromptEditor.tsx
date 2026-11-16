import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'

import { judgePromptsFor } from '../evaluationSnippets'
import { llmEvaluationLogic } from '../llmEvaluationLogic'

export function EvaluationPromptEditor(): JSX.Element {
    const { evaluation } = useValues(llmEvaluationLogic)
    const { setEvaluationPrompt, setTrueIsFailure } = useActions(llmEvaluationLogic)

    if (!evaluation || evaluation.evaluation_type !== 'llm_judge') {
        return <div>Loading...</div>
    }

    const prompt = evaluation.evaluation_config.prompt
    const allowsNA = evaluation.output_config.allows_na ?? false
    const templatePrompts = judgePromptsFor(evaluation)

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
                                  ? 'Describe how to score the response, within the range you set.'
                                  : allowsNA
                                    ? `Write a prompt that evaluates the LLM generation and returns true, false, or N/A if the check doesn't apply.

Example: Is this response mathematically accurate? Return true if correct, false if incorrect, or N/A if no math is involved.`
                                    : `Write a prompt that evaluates the LLM generation and returns true or false.

Example: Is this response helpful and accurate? Return true if yes, false if no.`
                        }
                        rows={4}
                        className="font-mono text-sm"
                        maxLength={2000}
                    />
                    {templatePrompts.length > 0 && (
                        <LemonMenu
                            items={templatePrompts.map(({ label, prompt: templatePrompt, trueIsFailure }) => ({
                                label,
                                onClick: () => {
                                    setEvaluationPrompt(templatePrompt)
                                    // A detector's prompt returns true for the problem, so its polarity comes with it.
                                    if (evaluation.output_type === 'boolean') {
                                        setTrueIsFailure(!!trueIsFailure)
                                    }
                                },
                            }))}
                        >
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                sideIcon={<IconChevronDown />}
                                data-attr="llma-evaluation-prompt-insert-template"
                            >
                                Start from a template
                            </LemonButton>
                        </LemonMenu>
                    )}
                </div>
            </LemonField.Pure>
        </div>
    )
}
