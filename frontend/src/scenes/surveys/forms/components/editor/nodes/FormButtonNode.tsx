import { Node, mergeAttributes } from '@tiptap/core'
import { Fragment, Node as ProseMirrorNode } from '@tiptap/pm/model'
import { Plugin, PluginKey, Transaction } from '@tiptap/pm/state'
import { NodeViewProps, NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import { useCallback, useEffect, useRef } from 'react'

type FormButtonVariant = 'next' | 'submit'

interface FormButtonStorage {
    onSubmitButtonTextChange?: (text: string) => void
}

const pluginKey = new PluginKey('formButtonReconciliation')

function getDefaultButtonText(variant: FormButtonVariant): string {
    return variant === 'submit' ? 'Submit' : 'Next'
}

function normalizeVariant(value: unknown): FormButtonVariant {
    return value === 'submit' ? 'submit' : 'next'
}

function normalizeTargetId(value: unknown): string | null {
    return typeof value === 'string' && value.trim().length > 0 ? value : null
}

function normalizeButtonText(value: unknown, variant: FormButtonVariant): string {
    return typeof value === 'string' && value.trim().length > 0 ? value.trim() : getDefaultButtonText(variant)
}

function isEmptyParagraphNode(node: ProseMirrorNode): boolean {
    return node.type.name === 'paragraph' && node.textContent.trim().length === 0 && node.childCount === 0
}

function areTopLevelNodesEqual(doc: ProseMirrorNode, desiredNodes: ProseMirrorNode[]): boolean {
    if (doc.childCount !== desiredNodes.length) {
        return false
    }

    for (let index = 0; index < desiredNodes.length; index++) {
        if (!doc.child(index).eq(desiredNodes[index])) {
            return false
        }
    }

    return true
}

function buildDesiredTopLevelNodes(
    doc: ProseMirrorNode,
    fallbackSubmitButtonText: string,
    nodeTypes: {
        formButton: ProseMirrorNode['type']
        formPageBreak: ProseMirrorNode['type']
        formThankYouBreak: ProseMirrorNode['type']
    }
): ProseMirrorNode[] {
    const nextButtonTextByTargetId = new Map<string, string>()
    let submitButtonText: string | null = null

    doc.forEach((node) => {
        if (node.type !== nodeTypes.formButton) {
            return
        }

        const variant = normalizeVariant(node.attrs.variant)
        const buttonText = normalizeButtonText(node.attrs.buttonText, variant)

        if (variant === 'next') {
            const targetId = normalizeTargetId(node.attrs.targetId)
            if (targetId && !nextButtonTextByTargetId.has(targetId)) {
                nextButtonTextByTargetId.set(targetId, buttonText)
            }
            return
        }

        if (submitButtonText === null) {
            submitButtonText = buttonText
        }
    })

    const desiredNodes: ProseMirrorNode[] = []
    let firstThankYouIndex: number | null = null
    let nonButtonNodeCount = 0

    doc.forEach((node) => {
        if (node.type === nodeTypes.formButton) {
            return
        }

        nonButtonNodeCount += 1

        if (node.type === nodeTypes.formPageBreak) {
            const targetId = normalizeTargetId(node.attrs.pageId)
            const legacyText =
                typeof node.attrs.buttonText === 'string' && node.attrs.buttonText.trim().length > 0
                    ? node.attrs.buttonText.trim()
                    : null
            const buttonText = targetId
                ? (nextButtonTextByTargetId.get(targetId) ?? legacyText ?? getDefaultButtonText('next'))
                : (legacyText ?? getDefaultButtonText('next'))

            desiredNodes.push(
                nodeTypes.formButton.create({
                    variant: 'next',
                    targetId,
                    buttonText,
                })
            )
        }

        if (node.type === nodeTypes.formThankYouBreak && firstThankYouIndex === null) {
            firstThankYouIndex = desiredNodes.length
        }

        desiredNodes.push(node)
    })

    const hasRealContent = desiredNodes.some(
        (node, index) => index > 0 && node.type !== nodeTypes.formButton && !isEmptyParagraphNode(node)
    )

    if (hasRealContent) {
        const submitText = submitButtonText ?? fallbackSubmitButtonText
        const submitNode = nodeTypes.formButton.create({
            variant: 'submit',
            targetId: null,
            buttonText: submitText,
        })

        const submitIndex = firstThankYouIndex ?? desiredNodes.length
        desiredNodes.splice(submitIndex, 0, submitNode)
    }

    return desiredNodes
}

function FormButtonNodeView({ editor, node, updateAttributes }: NodeViewProps): JSX.Element {
    const variant = normalizeVariant(node.attrs.variant)
    const buttonText = normalizeButtonText(node.attrs.buttonText, variant)
    const textRef = useRef<HTMLSpanElement>(null)
    const formButtonStorage = (editor.storage as unknown as Record<string, FormButtonStorage | undefined>).formButton

    useEffect(() => {
        const textElement = textRef.current

        if (!textElement || document.activeElement === textElement) {
            return
        }

        textElement.textContent = buttonText
    }, [buttonText])

    const commitText = useCallback((): void => {
        const textElement = textRef.current
        if (!textElement) {
            return
        }

        const nextText = normalizeButtonText(textElement.textContent, variant)
        textElement.textContent = nextText

        if (nextText === buttonText) {
            return
        }

        updateAttributes({ buttonText: nextText })

        if (variant === 'submit') {
            formButtonStorage?.onSubmitButtonTextChange?.(nextText)
        }
    }, [buttonText, formButtonStorage, updateAttributes, variant])

    return (
        <NodeViewWrapper className={`form-button form-button--${variant}`}>
            <div contentEditable={false} className="form-button__button">
                <span
                    ref={textRef}
                    className="form-button__text"
                    contentEditable
                    suppressContentEditableWarning
                    spellCheck={false}
                    onBlur={commitText}
                    onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                            event.preventDefault()
                            ;(event.currentTarget as HTMLSpanElement).blur()
                        }
                        event.stopPropagation()
                    }}
                    onMouseDown={(event) => {
                        event.stopPropagation()
                    }}
                >
                    {buttonText}
                </span>
            </div>
        </NodeViewWrapper>
    )
}

export const FormButtonNode = Node.create({
    name: 'formButton',

    group: 'block',

    atom: true,

    draggable: false,

    selectable: false,

    addOptions() {
        return {
            submitButtonText: 'Submit' as string,
            onSubmitButtonTextChange: undefined as ((text: string) => void) | undefined,
        }
    },

    addStorage() {
        return {
            onSubmitButtonTextChange: this.options.onSubmitButtonTextChange,
        }
    },

    addAttributes() {
        return {
            variant: {
                default: 'next',
                parseHTML: (element: HTMLElement) => normalizeVariant(element.getAttribute('data-variant')),
                renderHTML: (attributes: Record<string, unknown>) => ({
                    'data-variant': normalizeVariant(attributes.variant),
                }),
            },
            targetId: {
                default: null,
                parseHTML: (element: HTMLElement) => normalizeTargetId(element.getAttribute('data-target-id')),
                renderHTML: (attributes: Record<string, unknown>) => {
                    const targetId = normalizeTargetId(attributes.targetId)
                    return targetId ? { 'data-target-id': targetId } : {}
                },
            },
            buttonText: {
                default: 'Next',
                parseHTML: (element: HTMLElement) => {
                    const variant = normalizeVariant(element.getAttribute('data-variant'))
                    return normalizeButtonText(element.getAttribute('data-button-text'), variant)
                },
                renderHTML: (attributes: Record<string, unknown>) => {
                    const variant = normalizeVariant(attributes.variant)
                    return {
                        'data-button-text': normalizeButtonText(attributes.buttonText, variant),
                    }
                },
            },
        }
    },

    parseHTML() {
        return [{ tag: 'div[data-form-button]' }]
    },

    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes({ 'data-form-button': '' }, HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(FormButtonNodeView)
    },

    addProseMirrorPlugins() {
        const extension = this

        return [
            new Plugin({
                key: pluginKey,
                view(view) {
                    queueMicrotask(() => {
                        if (!view.isDestroyed) {
                            view.dispatch(view.state.tr.setMeta(pluginKey, { reconcile: true, source: 'init' }))
                        }
                    })

                    return {}
                },
                appendTransaction(transactions: readonly Transaction[], _oldState, newState) {
                    const shouldReconcile = transactions.some((transaction) => {
                        const pluginMeta = transaction.getMeta(pluginKey) as
                            | { reconcile?: boolean; reconciled?: boolean }
                            | undefined

                        return transaction.docChanged || pluginMeta?.reconcile === true
                    })

                    if (!shouldReconcile) {
                        return null
                    }

                    if (
                        transactions.some((transaction) => {
                            const pluginMeta = transaction.getMeta(pluginKey) as
                                | { reconcile?: boolean; reconciled?: boolean }
                                | undefined

                            return pluginMeta?.reconciled === true
                        })
                    ) {
                        return null
                    }

                    const formButton = newState.schema.nodes.formButton
                    const formPageBreak = newState.schema.nodes.formPageBreak
                    const formThankYouBreak = newState.schema.nodes.formThankYouBreak

                    if (!formButton || !formPageBreak || !formThankYouBreak) {
                        return null
                    }

                    const desiredNodes = buildDesiredTopLevelNodes(newState.doc, extension.options.submitButtonText, {
                        formButton,
                        formPageBreak,
                        formThankYouBreak,
                    })

                    if (areTopLevelNodesEqual(newState.doc, desiredNodes)) {
                        return null
                    }

                    const transaction = newState.tr.replaceWith(
                        0,
                        newState.doc.content.size,
                        Fragment.fromArray(desiredNodes)
                    )

                    transaction.setMeta('addToHistory', false)
                    transaction.setMeta(pluginKey, { reconciled: true })

                    return transaction
                },
            }),
        ]
    },
})
