import './TextCard.scss'

import { EditorContent } from '@tiptap/react'
import clsx from 'clsx'
import React, { memo, useEffect, useMemo } from 'react'

import { IconPencil } from '@posthog/icons'

import 'lib/components/Cards/CardMeta.scss'
import 'lib/components/MarkdownEditor/shared/RichMarkdownEditor.scss'
import { Resizeable } from 'lib/components/Cards/CardMeta'
import { DashboardResizeHandles } from 'lib/components/Cards/handles'
import { EditModeEdge, EditModeEdgeOverlay } from 'lib/components/Cards/InsightCard/EditModeEdgeOverlay'
import { useRichContentEditor } from 'lib/components/RichContentEditor'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More, MoreProps } from 'lib/lemon-ui/LemonButton/More'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { DashboardPlacement, DashboardTile, QueryBasedInsightModel } from '~/types'

import { markdownToTextCardDoc, TEXT_CARD_MARKDOWN_READONLY_EXTENSIONS } from './textCardMarkdown'

interface TextCardProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    textTile: DashboardTile<QueryBasedInsightModel>
    placement: DashboardPlacement
    children?: JSX.Element
    /** Whether hovering near the card edge should hint that edit mode is available. */
    canEnterEditModeFromEdge?: boolean
    /** Called when the user clicks an edge hint to enter edit mode. */
    onEnterEditModeFromEdge?: (event: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge) => void
    moreButtonOverlay?: MoreProps['overlay']
    /** Called when the user mousedowns on the card body (drag handle) in view mode to enter edit mode. */
    onDragHandleMouseDown?: React.MouseEventHandler<HTMLDivElement>
    /** Whether editing controls (three-dots menu) should be shown. False hides them on template dashboards in view mode. */
    showEditingControls?: boolean
    /** When set, rendered in place of the card body — used for inline markdown editing. */
    editingContent?: JSX.Element
    /** Called when the user clicks the card body to edit the markdown inline. */
    onStartInlineEdit?: () => void
    /** Called when the user clicks the hover pencil button to open the full editor. */
    onOpenFullEditor?: () => void
}

interface TextCardBodyProps extends Pick<React.HTMLAttributes<HTMLDivElement>, 'className'> {
    text: string
    closeDetails?: () => void
}

function TextContentImpl({ text, closeDetails, className }: TextCardBodyProps): JSX.Element {
    const initialDoc = useMemo(() => markdownToTextCardDoc(text), [text])

    const editor = useRichContentEditor({
        extensions: TEXT_CARD_MARKDOWN_READONLY_EXTENSIONS,
        initialContent: initialDoc,
        disabled: true,
    })

    useEffect(() => {
        if (!editor) {
            return
        }

        editor.commands.setContent(initialDoc, { emitUpdate: false })
    }, [editor, initialDoc])

    return (
        <div className={clsx('w-full', className)} onClick={() => closeDetails?.()}>
            {editor ? (
                <div className="RichMarkdownEditor overflow-auto">
                    <EditorContent editor={editor} className="RichMarkdownEditor__content px-0 py-0" />
                </div>
            ) : (
                <LemonMarkdown className="overflow-auto">{text}</LemonMarkdown>
            )}
        </div>
    )
}

export const TextContent = memo(TextContentImpl)
TextContent.displayName = 'TextContent'

function TextCardInternal(
    {
        textTile,
        showResizeHandles,
        children,
        className,
        moreButtonOverlay,
        placement,
        canEnterEditModeFromEdge,
        onEnterEditModeFromEdge,
        onDragHandleMouseDown,
        showEditingControls,
        editingContent,
        onStartInlineEdit,
        onOpenFullEditor,
        ...divProps
    }: TextCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    const { text } = textTile

    if (!text) {
        throw new Error('TextCard requires text')
    }

    const shouldHideMoreButton = placement === DashboardPlacement.Public || showEditingControls === false

    const isTransparent = textTile.transparent_background

    const inlineEditEnabled = !!onStartInlineEdit && !shouldHideMoreButton && !editingContent

    const handleBodyClick = (e: React.MouseEvent<HTMLDivElement>): void => {
        // Don't hijack link clicks or an in-progress text selection
        if ((e.target as Element | null)?.closest('a') || window.getSelection()?.toString()) {
            return
        }
        onStartInlineEdit?.()
    }

    return (
        <div
            className={clsx(
                'DashboardTileCard TextCard group rounded flex flex-col',
                !isTransparent && 'bg-surface-primary border',
                isTransparent && showResizeHandles && 'border border-dashed border-border',
                className
            )}
            data-attr="text-card"
            {...divProps}
            ref={ref}
        >
            {!shouldHideMoreButton && !editingContent && (
                <div className="absolute right-4 top-4 flex items-center gap-1">
                    {onOpenFullEditor && (
                        <LemonButton
                            size="small"
                            icon={<IconPencil />}
                            onClick={onOpenFullEditor}
                            tooltip="Open editor"
                            className="opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
                            data-attr="text-card-open-full-editor"
                            aria-label="Edit text"
                        />
                    )}
                    {moreButtonOverlay && <More overlay={moreButtonOverlay} />}
                </div>
            )}

            {editingContent ? (
                // Intentionally not TextCard__body — that class is the grid drag handle
                <div className="TextCard__editing flex min-h-0 w-full flex-1 flex-col">{editingContent}</div>
            ) : (
                <div
                    className={clsx(
                        'TextCard__body w-full',
                        inlineEditEnabled ? 'cursor-pointer' : onDragHandleMouseDown && 'cursor-grab'
                    )}
                    // Inline edit takes precedence over the drag-to-enter-layout-edit gesture on text cards
                    onMouseDown={inlineEditEnabled ? undefined : onDragHandleMouseDown}
                    onClick={inlineEditEnabled ? handleBodyClick : undefined}
                >
                    <TextContent text={text.body} className={shouldHideMoreButton ? 'p-4' : 'p-4 pr-14'} />
                </div>
            )}

            {canEnterEditModeFromEdge && !showResizeHandles && onEnterEditModeFromEdge && (
                <EditModeEdgeOverlay onEnterEditMode={onEnterEditModeFromEdge} />
            )}
            {showResizeHandles && <DashboardResizeHandles />}
            {children /* Extras, such as resize handles */}
        </div>
    )
}

export const TextCard = React.forwardRef<HTMLDivElement, TextCardProps>(TextCardInternal)
