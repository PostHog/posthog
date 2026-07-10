import clsx from 'clsx'
import {
    KeyboardEvent as ReactKeyboardEvent,
    type CSSProperties,
    useEffect,
    useLayoutEffect,
    useRef,
    useState,
} from 'react'

import { IconCode, IconComment, IconCopy, IconExternal, IconQuote, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { IconBold, IconItalic, IconLink } from 'lib/lemon-ui/icons'

import {
    FloatingToolbarCodeRange,
    FloatingToolbarListItemRange,
    FloatingToolbarState,
    FloatingToolbarTextRange,
    TextBlockStyle,
} from './editorTypes'
import { getSelectedLinkHref } from './inlineContent'
import { sanitizeNotebookLinkHref } from './markdown'
import { NotebookInlineMark, NotebookTextBlockNode } from './types'

export const TEXT_BLOCK_STYLE_BUTTONS: {
    style: TextBlockStyle
    label: string
    content?: string
    icon?: JSX.Element
}[] = [
    { style: 'paragraph', label: 'Text', content: 'Text' },
    { style: 1, label: 'Heading 1', content: 'H1' },
    { style: 2, label: 'Heading 2', content: 'H2' },
    { style: 3, label: 'Heading 3', content: 'H3' },
    { style: 'blockquote', label: 'Blockquote', icon: <IconQuote /> },
    { style: 'code', label: 'Code', icon: <IconCode /> },
]

export function FormattingToolbar({
    selectedBlockStyle,
    selectedBlockQuoted,
    placement,
    top,
    left,
    showInlineActions,
    applyInlineMark,
    applyInlineLink,
    currentLinkHref,
    initialLinkEditorOpen,
    setBlockStyle,
    copySelection,
    askAIAboutSelection,
    isAskAIDisabled,
    startInlineCommentAtSelection,
    lockPosition,
    returnFocusToEditor,
}: {
    selectedBlockStyle: TextBlockStyle | null
    /** Whether every selected block sits inside a blockquote — orthogonal to the text style. */
    selectedBlockQuoted: boolean
    placement: 'above' | 'below'
    top: number
    left: number
    showInlineActions: boolean
    applyInlineMark: (markType: NotebookInlineMark['type']) => void
    applyInlineLink: (href: string | null) => void
    currentLinkHref: string | null
    initialLinkEditorOpen: boolean
    setBlockStyle: (style: TextBlockStyle) => void
    copySelection: () => void
    askAIAboutSelection?: () => void
    isAskAIDisabled?: boolean
    startInlineCommentAtSelection?: () => void
    lockPosition: () => void
    /** Moves focus back into the editor (Escape while the toolbar holds focus). */
    returnFocusToEditor?: () => void
}): JSX.Element {
    const [isLinkEditorOpen, setIsLinkEditorOpen] = useState(initialLinkEditorOpen)
    const [linkHref, setLinkHref] = useState(currentLinkHref ?? '')
    const toolbarRef = useRef<HTMLDivElement | null>(null)
    const [boundsShift, setBoundsShift] = useState({ x: 0, y: 0 })

    // The anchor point only clamps the toolbar's center to the viewport, so the rendered toolbar
    // (translated -50% horizontally, and -100% when placed above) can still poke past the edges.
    // Measure the real box and shift it back inside.
    useLayoutEffect(() => {
        const element = toolbarRef.current
        if (!element) {
            return
        }

        const rect = element.getBoundingClientRect()
        if (!rect.width && !rect.height) {
            return
        }

        const margin = 8
        const baseLeft = rect.left - boundsShift.x
        const baseTop = rect.top - boundsShift.y
        let x = 0
        if (baseLeft + rect.width > window.innerWidth - margin) {
            x = window.innerWidth - margin - rect.width - baseLeft
        }
        if (baseLeft + x < margin) {
            x = margin - baseLeft
        }
        let y = 0
        if (baseTop + rect.height > window.innerHeight - margin) {
            y = window.innerHeight - margin - rect.height - baseTop
        }
        if (baseTop + y < margin) {
            y = margin - baseTop
        }

        x = Math.round(x)
        y = Math.round(y)
        if (x !== boundsShift.x || y !== boundsShift.y) {
            setBoundsShift({ x, y })
        }
    }, [top, left, placement, isLinkEditorOpen, showInlineActions, boundsShift])

    const toolbarStyle = {
        '--markdown-notebook-format-toolbar-top': `${top}px`,
        '--markdown-notebook-format-toolbar-left': `${left}px`,
        '--markdown-notebook-format-toolbar-shift-x': `${boundsShift.x}px`,
        '--markdown-notebook-format-toolbar-shift-y': `${boundsShift.y}px`,
    } as CSSProperties
    const normalizedLinkHref = sanitizeNotebookLinkHref(linkHref)
    const hasExistingLink = !!currentLinkHref

    useEffect(() => {
        if (initialLinkEditorOpen) {
            setLinkHref(currentLinkHref ?? '')
            setIsLinkEditorOpen(true)
            return
        }

        if (!isLinkEditorOpen) {
            setLinkHref(currentLinkHref ?? '')
        }
    }, [currentLinkHref, initialLinkEditorOpen, isLinkEditorOpen])

    const openLinkEditor = (): void => {
        setLinkHref(currentLinkHref ?? '')
        setIsLinkEditorOpen(true)
    }

    const setLink = (): void => {
        if (!normalizedLinkHref) {
            return
        }

        applyInlineLink(normalizedLinkHref)
        setIsLinkEditorOpen(false)
    }

    const removeLink = (): void => {
        applyInlineLink(null)
        setIsLinkEditorOpen(false)
    }

    // Roving arrow-key navigation between the toolbar's buttons; Escape hands focus back to
    // the editor. The buttons stay in the tab order, so this only augments focus movement.
    const handleToolbarKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>): void => {
        if (event.target instanceof HTMLElement && event.target.closest('.MarkdownNotebook__format-link-editor')) {
            if (event.key === 'Escape') {
                event.preventDefault()
                event.stopPropagation()
                setIsLinkEditorOpen(false)
            }
            return
        }

        if (event.key === 'Escape') {
            event.preventDefault()
            event.stopPropagation()
            returnFocusToEditor?.()
            return
        }

        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
            return
        }

        const toolbarElement = toolbarRef.current
        if (!toolbarElement) {
            return
        }

        const buttons = Array.from(toolbarElement.querySelectorAll<HTMLButtonElement>('button:not([disabled])'))
        if (!buttons.length) {
            return
        }

        const activeIndex = buttons.findIndex((button) => button === window.document.activeElement)
        if (activeIndex === -1) {
            return
        }

        event.preventDefault()
        event.stopPropagation()
        const nextIndex =
            event.key === 'Home'
                ? 0
                : event.key === 'End'
                  ? buttons.length - 1
                  : (activeIndex + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length
        buttons[nextIndex].focus()
    }

    return (
        <div
            className={clsx('MarkdownNotebook__format-toolbar', `MarkdownNotebook__format-toolbar--${placement}`)}
            contentEditable={false}
            ref={toolbarRef}
            style={toolbarStyle}
            role="toolbar"
            aria-label="Text formatting"
            aria-orientation="horizontal"
            aria-keyshortcuts="Alt+F10"
            onKeyDown={handleToolbarKeyDown}
            onFocusCapture={lockPosition}
            onPointerDownCapture={lockPosition}
            onTouchStartCapture={lockPosition}
            onMouseDown={(event) => {
                lockPosition()
                if (
                    event.target instanceof HTMLElement &&
                    event.target.closest('.MarkdownNotebook__format-link-editor')
                ) {
                    return
                }
                event.preventDefault()
            }}
        >
            <div
                className={clsx(
                    'MarkdownNotebook__format-style-buttons',
                    showInlineActions && 'MarkdownNotebook__format-style-buttons--separated'
                )}
                role="group"
                aria-label="Text style"
            >
                {TEXT_BLOCK_STYLE_BUTTONS.map((button) => {
                    // Quote membership is orthogonal to the text style, so a quoted heading lights up
                    // both its heading button and the quote button. The quote button always dispatches
                    // 'blockquote' — the editor toggles membership based on the selection's current state.
                    const isActive =
                        button.style === 'blockquote' ? selectedBlockQuoted : selectedBlockStyle === button.style
                    return (
                        <LemonButton
                            key={button.label}
                            size="xsmall"
                            icon={button.icon}
                            tooltip={button.label}
                            aria-label={button.label}
                            aria-pressed={isActive}
                            active={isActive}
                            className="MarkdownNotebook__format-style-button"
                            onClick={() =>
                                setBlockStyle(button.style === 'blockquote' || !isActive ? button.style : 'paragraph')
                            }
                        >
                            {button.content}
                        </LemonButton>
                    )
                })}
            </div>
            {showInlineActions ? (
                <>
                    <LemonButton
                        size="xsmall"
                        icon={<IconBold />}
                        tooltip="Bold"
                        aria-label="Bold"
                        onClick={() => applyInlineMark('bold')}
                    />
                    <LemonButton
                        size="xsmall"
                        icon={<IconItalic />}
                        tooltip="Italic"
                        aria-label="Italic"
                        onClick={() => applyInlineMark('italic')}
                    />
                    <LemonButton
                        size="xsmall"
                        tooltip="Underline"
                        aria-label="Underline"
                        onClick={() => applyInlineMark('underline')}
                    >
                        <span className="font-semibold underline">U</span>
                    </LemonButton>
                    <LemonButton
                        size="xsmall"
                        tooltip="Strikethrough"
                        aria-label="Strikethrough"
                        onClick={() => applyInlineMark('strike')}
                    >
                        <span className="font-semibold line-through">S</span>
                    </LemonButton>
                    <LemonButton
                        size="xsmall"
                        icon={<IconCode />}
                        tooltip="Inline code"
                        aria-label="Inline code"
                        onClick={() => applyInlineMark('code')}
                    />
                    <LemonButton
                        size="xsmall"
                        icon={<IconLink />}
                        tooltip="Link"
                        aria-label="Link"
                        aria-pressed={hasExistingLink || isLinkEditorOpen}
                        active={hasExistingLink || isLinkEditorOpen}
                        onClick={openLinkEditor}
                    />
                    <LemonButton
                        size="xsmall"
                        icon={<IconCopy />}
                        tooltip="Copy"
                        aria-label="Copy"
                        onClick={copySelection}
                    />
                </>
            ) : null}
            {startInlineCommentAtSelection ? (
                <LemonButton
                    size="xsmall"
                    icon={<IconComment />}
                    tooltip="Comment"
                    aria-label="Comment on selection"
                    onClick={startInlineCommentAtSelection}
                />
            ) : null}
            {showInlineActions && askAIAboutSelection ? (
                <LemonButton
                    size="xsmall"
                    icon={<IconSparkles />}
                    tooltip="Ask AI"
                    aria-label="Ask AI"
                    disabled={isAskAIDisabled}
                    disabledReason={isAskAIDisabled ? 'Ask AI is already active' : undefined}
                    onClick={askAIAboutSelection}
                />
            ) : null}
            {showInlineActions && isLinkEditorOpen ? (
                <div className="MarkdownNotebook__format-link-editor">
                    <LemonInput
                        size="small"
                        type="url"
                        placeholder="https://..."
                        aria-label="Link URL"
                        value={linkHref}
                        onChange={setLinkHref}
                        onPressEnter={setLink}
                        autoFocus
                        className="MarkdownNotebook__format-link-input"
                    />
                    {hasExistingLink && sanitizeNotebookLinkHref(currentLinkHref ?? '') ? (
                        <LemonButton
                            size="xsmall"
                            icon={<IconExternal />}
                            tooltip="Open link in new tab"
                            aria-label="Open link in new tab"
                            onClick={() => {
                                const href = sanitizeNotebookLinkHref(currentLinkHref ?? '')
                                if (href) {
                                    window.open(href, '_blank', 'noopener')
                                }
                            }}
                        />
                    ) : null}
                    {hasExistingLink ? (
                        <LemonButton size="xsmall" status="danger" onClick={removeLink}>
                            Remove
                        </LemonButton>
                    ) : null}
                    <LemonButton
                        size="xsmall"
                        type="primary"
                        onClick={setLink}
                        disabledReason={!normalizedLinkHref ? 'Enter an http or https URL' : undefined}
                    >
                        {hasExistingLink ? 'Update' : 'Set'}
                    </LemonButton>
                </div>
            ) : null}
        </div>
    )
}

export function getTextBlockStyle(node: NotebookTextBlockNode): TextBlockStyle {
    if (node.type === 'heading') {
        const level = node.level ?? 1
        return level === 1 || level === 2 || level === 3 ? level : 3
    }

    return node.type === 'blockquote' ? 'blockquote' : 'paragraph'
}

export function getSelectedBlockStyle(
    textRanges: FloatingToolbarTextRange[],
    codeRanges: FloatingToolbarCodeRange[],
    listItemRanges: FloatingToolbarListItemRange[] = []
): TextBlockStyle | null {
    // Plain list items map to `null` so a mixed selection never reports a shared style.
    const styles = new Set<TextBlockStyle | null>([
        ...textRanges.map(({ node }): TextBlockStyle | null => getTextBlockStyle(node)),
        ...codeRanges.map((): TextBlockStyle | null => 'code'),
        ...listItemRanges.map(({ node }): TextBlockStyle | null => (node.blockquote ? 'blockquote' : null)),
    ])

    if (styles.size !== 1) {
        return null
    }

    return [...styles][0]
}

/** True when the selection is non-empty and every selected block sits inside a blockquote. */
export function getSelectedBlocksQuoted(
    textRanges: FloatingToolbarTextRange[],
    codeRanges: FloatingToolbarCodeRange[],
    listItemRanges: FloatingToolbarListItemRange[] = []
): boolean {
    if (codeRanges.length || (!textRanges.length && !listItemRanges.length)) {
        return false
    }

    return (
        textRanges.every(({ node }) => node.type === 'blockquote' || !!node.blockquote) &&
        listItemRanges.every(({ node }) => !!node.blockquote)
    )
}

export function getSelectedTextBlockStyle(textRanges: FloatingToolbarTextRange[]): TextBlockStyle | null {
    const firstTextRange = textRanges[0]
    if (!firstTextRange) {
        return null
    }

    const firstStyle = getTextBlockStyle(firstTextRange.node)
    return textRanges.every(({ node }) => getTextBlockStyle(node) === firstStyle) ? firstStyle : null
}

/** The href shown in the link editor — only when exactly one inline range is selected. */
export function getFloatingToolbarLinkHref(toolbar: FloatingToolbarState): string | null {
    if (toolbar.codeRanges.length) {
        return null
    }

    if (toolbar.textRanges.length === 1 && toolbar.listItemRanges.length === 0) {
        return getSelectedLinkHref(toolbar.textRanges[0].node.children, toolbar.textRanges[0].range)
    }

    if (toolbar.listItemRanges.length === 1 && toolbar.textRanges.length === 0) {
        const { node, itemIndex, range } = toolbar.listItemRanges[0]
        return getSelectedLinkHref(node.items[itemIndex]?.children ?? [], range)
    }

    return null
}
