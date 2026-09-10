import { KeyboardEvent, Suspense, lazy, useEffect, useState } from 'react'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonLabel, LemonModal, LemonTextArea } from '@posthog/lemon-ui'
import { PostHogErrorBoundary } from '@posthog/react'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { updateNotebookCodeBlockText } from './documentModel'
import { InsertMenuSelectionDirection } from './editorTypes'
import { NotebookBlockNode, NotebookCodeBlockNode, NotebookMode } from './types'

// Loaded on demand so the mermaid library ships in its own chunk rather than the notebook bundle.
const LazyMermaidDiagram = lazy(() => import('lib/lemon-ui/LemonMarkdown/MermaidDiagram'))

// Wait for a pause in typing before re-rendering the preview, so a burst of keystrokes runs one
// Mermaid render instead of one parse and layout per character.
const MERMAID_PREVIEW_DEBOUNCE_MS = 250

export function NotebookMermaidBlock({
    node,
    mode,
    setBlockRef,
    updateNode,
    deleteNode,
    deleteSelectedNotebookBlocks,
    insertParagraphAfterNode,
    moveFocusToAdjacentNode,
    onInteractionStateChange,
}: {
    node: NotebookCodeBlockNode
    mode: NotebookMode
    setBlockRef: (element: HTMLElement | null) => void
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
    deleteNode: () => void
    deleteSelectedNotebookBlocks: () => boolean
    insertParagraphAfterNode: () => void
    moveFocusToAdjacentNode: (nodeId: string, direction: InsertMenuSelectionDirection, offset: number) => boolean
    onInteractionStateChange?: (isInteractionActive: boolean) => void
}): JSX.Element {
    const [isEditorOpen, setIsEditorOpen] = useState(false)
    const [draft, setDraft] = useState(node.text)
    const debouncedDraft = useDebouncedValue(draft, MERMAID_PREVIEW_DEBOUNCE_MS)
    const previewCode = isEditorOpen ? debouncedDraft : node.text

    const openEditor = (): void => {
        onInteractionStateChange?.(true)
        setDraft(node.text)
        setIsEditorOpen(true)
    }

    const closeEditor = (): void => {
        setIsEditorOpen(false)
        setDraft(node.text)
    }

    useEffect(() => {
        if (!isEditorOpen) {
            return
        }

        return () => onInteractionStateChange?.(false)
    }, [isEditorOpen, onInteractionStateChange])

    const saveDiagram = (): void => {
        if (draft !== node.text) {
            updateNode(node.id, (currentNode) => {
                if (currentNode.type !== 'code') {
                    return currentNode
                }
                return updateNotebookCodeBlockText(currentNode, draft)
            })
        }
        setIsEditorOpen(false)
    }

    // The rendered diagram has no caret, so it uses the keyboard contract for atomic notebook blocks.
    const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
        if (mode !== 'edit' || event.target !== event.currentTarget) {
            return
        }

        if (event.key === 'Backspace' || event.key === 'Delete') {
            event.preventDefault()
            if (!deleteSelectedNotebookBlocks()) {
                deleteNode()
            }
            return
        }

        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            if (moveFocusToAdjacentNode(node.id, event.key === 'ArrowDown' ? 'next' : 'previous', 0)) {
                event.preventDefault()
            }
            return
        }

        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            insertParagraphAfterNode()
        }
    }

    const renderPreview = (code: string, naturalWidth: boolean): JSX.Element => (
        <PostHogErrorBoundary
            key={code}
            additionalProperties={{
                feature: 'markdown_notebook_mermaid',
                markdown_notebook_node_id: node.id,
            }}
            fallback={() => (
                <div className="text-danger" data-attr="mermaid-error-boundary">
                    <div className="mb-1 text-xs">
                        This diagram couldn't render. Check the Mermaid definition or reload the page.
                    </div>
                    <CodeSnippet language={Language.Text} compact wrap>
                        {code}
                    </CodeSnippet>
                </div>
            )}
        >
            <Suspense
                fallback={
                    <div className="flex items-center justify-center p-4">
                        <Spinner />
                    </div>
                }
            >
                <LazyMermaidDiagram code={code} naturalWidth={naturalWidth} />
            </Suspense>
        </PostHogErrorBoundary>
    )

    return (
        <div
            className="MarkdownNotebook__mermaid-block"
            ref={setBlockRef}
            contentEditable={false}
            tabIndex={mode === 'edit' ? 0 : undefined}
            role="group"
            aria-label="Mermaid diagram"
            data-markdown-notebook-node-id={node.id}
            onKeyDown={handleKeyDown}
        >
            <div className="MarkdownNotebook__mermaid-preview">{renderPreview(node.text, true)}</div>
            {mode === 'edit' ? (
                <div className="MarkdownNotebook__mermaid-actions">
                    <LemonButton
                        size="xsmall"
                        icon={<IconPencil />}
                        tooltip="Edit diagram"
                        aria-label="Edit diagram"
                        data-attr="notebook-mermaid-edit"
                        onClick={openEditor}
                    />
                </div>
            ) : null}
            <LemonModal
                isOpen={isEditorOpen}
                onClose={closeEditor}
                title="Edit Mermaid diagram"
                description="Update the Mermaid definition and check the preview before saving."
                width="60rem"
                maxWidth="calc(100vw - 2rem)"
                hasUnsavedInput={draft !== node.text}
                data-attr="notebook-mermaid-editor"
                footer={
                    <>
                        <LemonButton type="secondary" data-attr="notebook-mermaid-editor-cancel" onClick={closeEditor}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            data-attr="notebook-mermaid-editor-save"
                            disabledReason={draft === node.text ? 'No changes to save' : undefined}
                            onClick={saveDiagram}
                        >
                            Save diagram
                        </LemonButton>
                    </>
                }
            >
                <div className="@container">
                    <div className="grid grid-cols-1 @3xl:grid-cols-2 gap-4">
                        <div className="flex min-w-0 flex-col gap-2">
                            <LemonLabel htmlFor={`mermaid-definition-${node.id}`}>Definition</LemonLabel>
                            <LemonTextArea
                                id={`mermaid-definition-${node.id}`}
                                value={draft}
                                aria-label="Mermaid definition"
                                data-attr="notebook-mermaid-definition"
                                className="font-mono"
                                minRows={16}
                                maxRows={24}
                                autoFocus
                                stopPropagation
                                onChange={setDraft}
                                onPressCmdEnter={saveDiagram}
                            />
                        </div>
                        <div className="flex min-w-0 flex-col gap-2">
                            <LemonLabel>Preview</LemonLabel>
                            <div className="min-h-72 max-h-96 overflow-auto rounded border bg-surface-primary p-3">
                                {renderPreview(previewCode, false)}
                            </div>
                        </div>
                    </div>
                </div>
            </LemonModal>
        </div>
    )
}
