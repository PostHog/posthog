import { MutableRefObject } from 'react'

import { CommentBlock } from './CommentBlock'
import { ComponentPanel, ComponentPanelVisibility } from './componentPanels'
import { DividerBlock } from './DividerBlock'
import {
    isCommentComponentNode,
    isDiscussionCommentNode,
    isDividerComponentNode,
    isPromptComponentNode,
} from './documentModel'
import { EditableCodeBlock } from './EditableCodeBlock'
import { EditableListBlock } from './EditableListBlock'
import { EditablePromptComponent } from './EditablePromptComponent'
import { EditableTableBlock } from './EditableTableBlock'
import { EditableTextBlock } from './EditableTextBlock'
import {
    InsertMenuSelectionDirection,
    InsertMenuState,
    RestoreSelectionRequest,
    TableCellPosition,
    TextSelectionPointerStartEvent,
} from './editorTypes'
import { MemoizedNotebookComponentShell } from './NotebookComponentShell'
import { isMermaidCodeBlock, NotebookMermaidBlock } from './NotebookMermaidBlock'
import { NotebookBlockNode, NotebookComponentRegistry, NotebookMode } from './types'

export function renderNode({
    node,
    nodeIndex,
    mode,
    placeholder,
    registry,
    componentPanels,
    rememberedComponentPanels,
    persistComponentPanelVisibility,
    isSelected,
    toggleComponentPanel,
    setLocalComponentPanels,
    rememberComponentPanels,
    setBlockRef,
    setListItemRef,
    setTableCellRef,
    updateNode,
    replaceNodeWithNodes,
    deleteNode,
    deleteNodeAndFocusAdjacent,
    deleteNodeAndFocusPrevious,
    deleteSelectedNotebookBlocks,
    insertParagraphAfterNode,
    deleteNodeBefore,
    moveFocusToAdjacentNode,
    openInsertMenu,
    openDetachedInsertMenu,
    updateAIPromptQuery,
    closeInsertMenu,
    moveInsertMenuSelection,
    toggleInsertMenu,
    activateInlineInsertMenuButton,
    showInlineInsertMenuButton,
    isInlineInsertMenuButtonVisible,
    isInsertMenuOpen,
    insertMenuMode,
    hasInvalidInsertMenuQuery,
    isAIWriting,
    isAIWritingPlaceholder,
    isAIPromptSubmitDisabled,
    aiPromptFocusRequest,
    submitInsertMenuSelection,
    submitAIPrompt,
    handleSelectionChange,
    startTextSelectionPointer,
    restoreSelectionRef,
    rootEditableInputHtmlByNodeIdRef,
}: {
    node: NotebookBlockNode
    nodeIndex: number
    mode: NotebookMode
    placeholder: string | undefined
    registry: NotebookComponentRegistry
    componentPanels: ComponentPanelVisibility
    rememberedComponentPanels?: ComponentPanelVisibility
    persistComponentPanelVisibility: boolean
    isSelected: boolean
    toggleComponentPanel: (panel: ComponentPanel) => void
    setLocalComponentPanels: (nodeId: string, panels: ComponentPanelVisibility) => void
    rememberComponentPanels: (nodeId: string, panels: ComponentPanelVisibility) => void
    setBlockRef: (element: HTMLElement | null) => void
    setListItemRef: (itemIndex: number, itemId: string | undefined, element: HTMLElement | null) => void
    setTableCellRef: (position: TableCellPosition, element: HTMLElement | null) => void
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
    replaceNodeWithNodes: (nodeId: string, replacementNodes: NotebookBlockNode[]) => void
    deleteNode: () => void
    deleteNodeAndFocusAdjacent: () => void
    deleteNodeAndFocusPrevious: (nodeId: string) => boolean
    deleteSelectedNotebookBlocks: () => boolean
    insertParagraphAfterNode: () => void
    deleteNodeBefore: (nodeId: string, options?: { requireSameTextStyle?: boolean }) => boolean
    moveFocusToAdjacentNode: (nodeId: string, direction: InsertMenuSelectionDirection, offset: number) => boolean
    openInsertMenu: (query?: string) => void
    openDetachedInsertMenu: () => boolean
    updateAIPromptQuery: (query: string) => void
    closeInsertMenu: () => void
    moveInsertMenuSelection: (direction: InsertMenuSelectionDirection) => void
    toggleInsertMenu: () => void
    activateInlineInsertMenuButton: () => void
    showInlineInsertMenuButton: boolean
    isInlineInsertMenuButtonVisible: boolean
    isInsertMenuOpen: boolean
    insertMenuMode: InsertMenuState['mode'] | null
    hasInvalidInsertMenuQuery: boolean
    isAIWriting: boolean
    isAIWritingPlaceholder: boolean
    isAIPromptSubmitDisabled: boolean
    aiPromptFocusRequest?: number
    submitInsertMenuSelection: (queryOverride?: string) => boolean
    submitAIPrompt: (queryOverride?: string) => boolean
    handleSelectionChange: () => void
    startTextSelectionPointer: (event: TextSelectionPointerStartEvent) => void
    restoreSelectionRef: MutableRefObject<RestoreSelectionRequest | null>
    rootEditableInputHtmlByNodeIdRef: MutableRefObject<Record<string, string>>
}): JSX.Element {
    if (node.type === 'component') {
        if (isDividerComponentNode(node)) {
            return (
                <DividerBlock
                    node={node}
                    mode={mode}
                    isSelected={isSelected}
                    setBlockRef={setBlockRef}
                    deleteNode={deleteNode}
                    deleteSelectedNotebookBlocks={deleteSelectedNotebookBlocks}
                    insertParagraphAfterNode={insertParagraphAfterNode}
                    moveFocusToAdjacentNode={moveFocusToAdjacentNode}
                />
            )
        }

        // Discussion comments (ref/replies) render through the registry shell; only the
        // authorial note flavor uses the inline chip.
        if (isCommentComponentNode(node) && !isDiscussionCommentNode(node)) {
            return (
                <CommentBlock
                    node={node}
                    mode={mode}
                    isSelected={isSelected}
                    setBlockRef={setBlockRef}
                    updateNode={updateNode}
                    deleteNode={deleteNode}
                    deleteSelectedNotebookBlocks={deleteSelectedNotebookBlocks}
                    insertParagraphAfterNode={insertParagraphAfterNode}
                    moveFocusToAdjacentNode={moveFocusToAdjacentNode}
                />
            )
        }

        if (isPromptComponentNode(node)) {
            return (
                <EditablePromptComponent
                    node={node}
                    mode={mode}
                    setBlockRef={setBlockRef}
                    updateNode={updateNode}
                    deleteNodeAndFocusAdjacent={deleteNodeAndFocusAdjacent}
                    updateAIPromptQuery={updateAIPromptQuery}
                    submitAIPrompt={submitAIPrompt}
                    isAIPromptSubmitDisabled={isAIPromptSubmitDisabled}
                    isActive={isInsertMenuOpen && insertMenuMode === 'ai'}
                    focusRequest={aiPromptFocusRequest}
                    restoreSelectionRef={restoreSelectionRef}
                />
            )
        }

        return (
            <MemoizedNotebookComponentShell
                node={node}
                mode={mode}
                componentPanels={componentPanels}
                isSelected={isSelected}
                registry={registry}
                toggleComponentPanel={toggleComponentPanel}
                rememberedComponentPanels={rememberedComponentPanels}
                persistComponentPanelVisibility={persistComponentPanelVisibility}
                setLocalComponentPanels={setLocalComponentPanels}
                rememberComponentPanels={rememberComponentPanels}
                setBlockRef={setBlockRef}
                updateNode={updateNode}
                deleteNode={deleteNode}
                deleteSelectedNotebookBlocks={deleteSelectedNotebookBlocks}
                insertParagraphAfterNode={insertParagraphAfterNode}
                moveFocusToAdjacentNode={moveFocusToAdjacentNode}
            />
        )
    }

    if (node.type === 'list') {
        return (
            <EditableListBlock
                node={node}
                mode={mode}
                setBlockRef={setBlockRef}
                setListItemRef={setListItemRef}
                updateNode={updateNode}
                handleSelectionChange={handleSelectionChange}
                startTextSelectionPointer={startTextSelectionPointer}
                restoreSelectionRef={restoreSelectionRef}
            />
        )
    }

    if (node.type === 'table') {
        return (
            <EditableTableBlock
                node={node}
                mode={mode}
                setBlockRef={setBlockRef}
                setTableCellRef={setTableCellRef}
                updateNode={updateNode}
                handleSelectionChange={handleSelectionChange}
                startTextSelectionPointer={startTextSelectionPointer}
                restoreSelectionRef={restoreSelectionRef}
            />
        )
    }

    if (node.type === 'code') {
        // Render mermaid fences as diagrams in view mode; edit mode keeps the source editable.
        if (mode === 'view' && isMermaidCodeBlock(node)) {
            return <NotebookMermaidBlock node={node} setBlockRef={setBlockRef} />
        }

        return (
            <EditableCodeBlock
                node={node}
                mode={mode}
                setBlockRef={setBlockRef}
                updateNode={updateNode}
                deleteSelectedNotebookBlocks={deleteSelectedNotebookBlocks}
                handleSelectionChange={handleSelectionChange}
                startTextSelectionPointer={startTextSelectionPointer}
            />
        )
    }

    return (
        <EditableTextBlock
            node={node}
            isTitleBlock={nodeIndex === 0}
            mode={mode}
            placeholder={placeholder}
            setBlockRef={setBlockRef}
            updateNode={updateNode}
            replaceNodeWithNodes={replaceNodeWithNodes}
            deleteSelectedNotebookBlocks={deleteSelectedNotebookBlocks}
            deleteNodeAndFocusPrevious={deleteNodeAndFocusPrevious}
            deleteNodeBefore={deleteNodeBefore}
            moveFocusToAdjacentNode={moveFocusToAdjacentNode}
            openInsertMenu={openInsertMenu}
            openDetachedInsertMenu={openDetachedInsertMenu}
            closeInsertMenu={closeInsertMenu}
            moveInsertMenuSelection={moveInsertMenuSelection}
            toggleInsertMenu={toggleInsertMenu}
            activateInlineInsertMenuButton={activateInlineInsertMenuButton}
            showInlineInsertMenuButton={showInlineInsertMenuButton}
            isInlineInsertMenuButtonVisible={isInlineInsertMenuButtonVisible}
            isInsertMenuOpen={isInsertMenuOpen}
            insertMenuMode={insertMenuMode}
            hasInvalidInsertMenuQuery={hasInvalidInsertMenuQuery}
            isAIWriting={isAIWriting}
            isAIWritingPlaceholder={isAIWritingPlaceholder}
            submitInsertMenuSelection={submitInsertMenuSelection}
            handleSelectionChange={handleSelectionChange}
            startTextSelectionPointer={startTextSelectionPointer}
            restoreSelectionRef={restoreSelectionRef}
            rootEditableInputHtmlByNodeIdRef={rootEditableInputHtmlByNodeIdRef}
        />
    )
}
