import clsx from 'clsx'
import { KeyboardEvent, MutableRefObject, useCallback, useEffect, useRef, useState } from 'react'

import { IconSend, IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { getNotebookStringProp, isPromptComponentNode } from './documentModel'
import { RestoreSelectionRequest } from './editorTypes'
import { NotebookBlockNode, NotebookComponentBlockNode, NotebookMode } from './types'

export function EditablePromptComponent({
    node,
    mode,
    setBlockRef,
    updateNode,
    deleteNodeAndFocusAdjacent,
    updateAIPromptQuery,
    submitAIPrompt,
    isAIPromptSubmitDisabled,
    isActive,
    focusRequest,
    restoreSelectionRef,
}: {
    node: NotebookComponentBlockNode
    mode: NotebookMode
    setBlockRef: (element: HTMLElement | null) => void
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
    deleteNodeAndFocusAdjacent: () => void
    updateAIPromptQuery: (query: string) => void
    submitAIPrompt: (queryOverride?: string) => boolean
    isAIPromptSubmitDisabled: boolean
    isActive: boolean
    focusRequest?: number
    restoreSelectionRef: MutableRefObject<RestoreSelectionRequest | null>
}): JSX.Element {
    const elementRef = useRef<HTMLTextAreaElement | null>(null)
    const handledFocusRequestRef = useRef<number | undefined>(undefined)
    const [isCollapsed, setIsCollapsed] = useState(false)
    const question = getNotebookStringProp(node.props.question) ?? ''
    const isEmpty = question.length === 0
    const submitDisabledReason = question.trim()
        ? isAIPromptSubmitDisabled
            ? 'AI is already running'
            : undefined
        : 'Write a prompt first'

    const setElementRef = useCallback(
        (element: HTMLTextAreaElement | null): void => {
            elementRef.current = element
            setBlockRef(element)
        },
        [setBlockRef]
    )

    useEffect(() => {
        if (isActive) {
            setIsCollapsed(false)
        }
    }, [isActive])

    useEffect(() => {
        if (focusRequest !== undefined && handledFocusRequestRef.current !== focusRequest && isCollapsed) {
            setIsCollapsed(false)
        }
    }, [focusRequest, isCollapsed])

    useEffect(() => {
        const element = elementRef.current
        if (!isActive || !element || document.activeElement === element) {
            return
        }

        element.focus()
        element.setSelectionRange(question.length, question.length)
    }, [isActive, question.length])

    useEffect(() => {
        const element = elementRef.current
        if (focusRequest === undefined || handledFocusRequestRef.current === focusRequest || !element) {
            return
        }

        if (document.activeElement === element) {
            handledFocusRequestRef.current = focusRequest
            return
        }

        element.focus()
        element.setSelectionRange(question.length, question.length)
        handledFocusRequestRef.current = focusRequest
    }, [focusRequest, question.length, isCollapsed])

    const updateQuestion = (nextQuestion: string): void => {
        updateNode(node.id, (currentNode) => {
            if (!isPromptComponentNode(currentNode)) {
                return currentNode
            }
            return {
                ...currentNode,
                props: {
                    ...currentNode.props,
                    question: nextQuestion,
                },
            }
        })
        updateAIPromptQuery(nextQuestion)
    }

    const submitPrompt = (query: string = question): void => {
        if (isAIPromptSubmitDisabled) {
            return
        }
        submitAIPrompt(query)
    }

    const deletePrompt = (): void => {
        deleteNodeAndFocusAdjacent()
    }

    const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>): void => {
        event.stopPropagation()

        if (event.key === 'Enter' && !event.nativeEvent.isComposing && !event.shiftKey) {
            event.preventDefault()
            submitPrompt(event.currentTarget.value)
            return
        }

        if (event.key === 'Backspace' || event.key === 'Delete') {
            const selectionStart = event.currentTarget.selectionStart ?? 0
            const selectionEnd = event.currentTarget.selectionEnd ?? selectionStart
            if (selectionStart !== selectionEnd) {
                const target = event.currentTarget
                const nextQuestion = `${question.slice(0, selectionStart)}${question.slice(selectionEnd)}`

                event.preventDefault()
                updateQuestion(nextQuestion)
                requestAnimationFrame(() => target.setSelectionRange(selectionStart, selectionStart))
                return
            }

            if (event.key === 'Backspace' && selectionStart === 0 && selectionEnd === 0) {
                event.preventDefault()
                updateNode(node.id, (currentNode) => {
                    if (!isPromptComponentNode(currentNode)) {
                        return currentNode
                    }
                    return {
                        id: currentNode.id,
                        type: 'paragraph',
                        children: question ? [{ type: 'text', text: question }] : [],
                    }
                })
                restoreSelectionRef.current = { nodeId: node.id, start: 0, end: 0 }
                return
            }

            if (event.key === 'Delete' && isEmpty) {
                event.preventDefault()
                deletePrompt()
            }
        }
    }

    return (
        <div
            className={clsx(
                'MarkdownNotebook__text-row',
                'MarkdownNotebook__text-row--ai-prompt',
                'MarkdownNotebook__text-row--inline-menu-visible'
            )}
        >
            <div
                className="MarkdownNotebook__ai-prompt-card"
                contentEditable={false}
                data-markdown-notebook-node-id={node.id}
            >
                <div className="MarkdownNotebook__ai-prompt-header">
                    <button
                        type="button"
                        className="MarkdownNotebook__ai-prompt-heading"
                        aria-expanded={!isCollapsed}
                        onClick={() => setIsCollapsed((currentValue) => !currentValue)}
                    >
                        <span className="MarkdownNotebook__ai-prompt-tag" aria-label="Ask AI prompt">
                            Ask AI:
                        </span>
                    </button>
                </div>
                {isCollapsed ? null : (
                    <div className="MarkdownNotebook__ai-prompt-form">
                        <textarea
                            ref={setElementRef}
                            className="MarkdownNotebook__ai-prompt-input MarkdownNotebook__text-block--ai-prompt"
                            data-attr="markdown-notebook-ai-prompt"
                            value={question}
                            onChange={(event) => {
                                event.stopPropagation()
                                updateQuestion(event.currentTarget.value)
                            }}
                            onKeyDown={handleKeyDown}
                            placeholder=""
                            autoFocus={isActive}
                            disabled={mode !== 'edit'}
                            rows={1}
                        />
                        <LemonButton
                            type="primary"
                            size="xsmall"
                            icon={<IconSend />}
                            tooltip="Send prompt"
                            aria-label="Send prompt"
                            onClick={() => submitPrompt()}
                            disabled={!!submitDisabledReason || mode !== 'edit'}
                            disabledReason={submitDisabledReason}
                        />
                    </div>
                )}
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    status="danger"
                    icon={<IconTrash />}
                    tooltip="Delete prompt"
                    aria-label="Delete prompt"
                    onClick={deletePrompt}
                />
            </div>
        </div>
    )
}
