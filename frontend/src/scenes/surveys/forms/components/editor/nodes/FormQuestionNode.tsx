import { Node, mergeAttributes } from '@tiptap/core'
import { NodeViewProps, NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import { useCallback } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import { FormQuestion, FormQuestionType } from 'scenes/surveys/forms/formTypes'

import { getDefaultQuestion, QUESTION_TYPE_REGISTRY } from '../../questions/questionTypeRegistry'

export function parseQuestionData(data: unknown): FormQuestion {
    if (typeof data === 'string') {
        try {
            return JSON.parse(data) as FormQuestion
        } catch {
            return getDefaultQuestion(FormQuestionType.ShortText).question
        }
    }
    if (data && typeof data === 'object') {
        return data as FormQuestion
    }
    return getDefaultQuestion(FormQuestionType.ShortText).question
}

function FormQuestionNodeView({ node, updateAttributes, selected }: NodeViewProps): JSX.Element {
    const questionData = parseQuestionData(node.attrs.questionData)
    const { icon, label, Preview } = QUESTION_TYPE_REGISTRY[questionData.type]

    const updateQuestion = useCallback(
        (updated: FormQuestion): void => {
            updateAttributes({ questionData: JSON.stringify(updated) })
        },
        [updateAttributes]
    )

    const updateQuestionText = useCallback(
        (value: string): void => {
            updateQuestion({ ...questionData, question: value })
        },
        [questionData, updateQuestion]
    )

    return (
        <NodeViewWrapper className={`form-question-node ${selected ? 'form-question-node--selected' : ''}`}>
            <div contentEditable={false} className="form-question-node__inner">
                <div className="flex items-center gap-1.5 mb-1">
                    <span className="text-muted">{icon}</span>
                    <span className="text-xs text-muted font-medium uppercase tracking-wide">{label}</span>
                    {!questionData.optional && <span className="text-xs text-danger font-medium">*</span>}
                </div>

                <LemonInput
                    value={questionData.question}
                    onChange={updateQuestionText}
                    placeholder="Enter your question..."
                    fullWidth
                    className="font-semibold text-base border-none"
                />

                <Preview question={questionData} onUpdate={updateQuestion} />
            </div>
        </NodeViewWrapper>
    )
}

export const FormQuestionNode = Node.create({
    name: 'formQuestion',

    group: 'block',

    atom: true,

    selectable: false,

    draggable: true,

    addAttributes() {
        return {
            questionId: {
                default: null,
                parseHTML: (element: HTMLElement) => element.getAttribute('data-question-id'),
                renderHTML: (attributes: Record<string, unknown>) => ({
                    'data-question-id': attributes.questionId,
                }),
            },
            questionData: {
                default: JSON.stringify(getDefaultQuestion(FormQuestionType.ShortText).question),
                parseHTML: (element: HTMLElement) => element.getAttribute('data-question'),
                renderHTML: (attributes: Record<string, unknown>) => ({
                    'data-question': attributes.questionData,
                }),
            },
        }
    },

    parseHTML() {
        return [{ tag: 'div[data-form-question]' }]
    },

    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes({ 'data-form-question': '' }, HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(FormQuestionNodeView)
    },

    addCommands() {
        return {
            insertFormQuestion:
                (attrs: { questionId: string; question: FormQuestion }) =>
                ({ commands }) => {
                    return commands.insertContent([
                        {
                            type: this.name,
                            attrs: {
                                questionId: attrs.questionId,
                                questionData: JSON.stringify(attrs.question),
                                focusOnMount: true,
                            },
                        },
                        { type: 'paragraph' },
                    ])
                },
        }
    },
})

declare module '@tiptap/core' {
    interface Commands<ReturnType> {
        formQuestion: {
            insertFormQuestion: (attrs: { questionId: string; question: FormQuestion }) => ReturnType
        }
    }
}
