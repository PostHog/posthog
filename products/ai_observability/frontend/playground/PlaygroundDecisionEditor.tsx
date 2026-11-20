import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { DecisionQuestionEditor } from './DecisionQuestionEditor'
import { llmPlaygroundPromptsLogic } from './llmPlaygroundPromptsLogic'
import { llmPlaygroundRunLogic } from './llmPlaygroundRunLogic'
import { llmPlaygroundVariablesLogic } from './llmPlaygroundVariablesLogic'
import { MAX_DECISION_QUESTIONS, createPlaygroundQuestion } from './playgroundDecisions'
import { TemplateVariableTextArea } from './TemplateVariableTextArea'

export function PlaygroundDecisionEditor({ promptId }: { promptId: string }): JSX.Element | null {
    const { promptConfigs } = useValues(llmPlaygroundPromptsLogic)
    const { setDecisionInput, setDecisionQuestions } = useActions(llmPlaygroundPromptsLogic)
    const { submitting } = useValues(llmPlaygroundRunLogic)
    const { submitPrompt } = useActions(llmPlaygroundRunLogic)
    const { unfilledVariables } = useValues(llmPlaygroundVariablesLogic)
    const prompt = promptConfigs.find((candidate) => candidate.id === promptId)

    if (!prompt) {
        return null
    }

    const questions = prompt.decisionQuestions
    const disabledReason = submitting ? 'Wait for the run to finish' : undefined

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1">
                <div className="text-xs font-semibold">Input</div>
                <TemplateVariableTextArea
                    value={prompt.decisionInput}
                    onChange={(decisionInput) => setDecisionInput(decisionInput, promptId)}
                    unfilledVariables={unfilledVariables}
                    placeholder="Paste the text to judge, for example a conversation or a support ticket"
                    minRows={6}
                    onPressCmdEnter={() => submitPrompt()}
                />
            </div>
            <div className="flex flex-col gap-2">
                <div>
                    <div className="text-xs font-semibold">Questions</div>
                    <div className="text-xs text-secondary">
                        The model answers each question about the input, with a probability for every answer.
                    </div>
                </div>
                {questions.map((question) => (
                    <DecisionQuestionEditor
                        key={question.id}
                        question={question}
                        disabledReason={disabledReason}
                        onChange={(updated) =>
                            setDecisionQuestions(
                                questions.map((candidate) => (candidate.id === updated.id ? updated : candidate)),
                                promptId
                            )
                        }
                        onRemove={() =>
                            setDecisionQuestions(
                                questions.filter((candidate) => candidate.id !== question.id),
                                promptId
                            )
                        }
                    />
                ))}
                <div>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPlus />}
                        onClick={() => setDecisionQuestions([...questions, createPlaygroundQuestion()], promptId)}
                        disabledReason={
                            disabledReason ??
                            (questions.length >= MAX_DECISION_QUESTIONS
                                ? `Ask at most ${MAX_DECISION_QUESTIONS} questions at once`
                                : undefined)
                        }
                        data-attr="llma-playground-decision-add-question"
                    >
                        Question
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
