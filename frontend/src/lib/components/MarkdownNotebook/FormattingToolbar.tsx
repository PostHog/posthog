import clsx from 'clsx'
import { type CSSProperties, useEffect, useState } from 'react'

import { IconCode, IconCopy, IconQuote, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { IconBold, IconItalic, IconLink } from 'lib/lemon-ui/icons'

import { FloatingToolbarCodeRange, FloatingToolbarState, FloatingToolbarTextRange, TextBlockStyle } from './editorTypes'
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
    { style: 'blockquote', label: 'Quote', icon: <IconQuote /> },
    { style: 'code', label: 'Code', icon: <IconCode /> },
]

export function FormattingToolbar({
    selectedBlockStyle,
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
    lockPosition,
}: {
    selectedBlockStyle: TextBlockStyle | null
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
    lockPosition: () => void
}): JSX.Element {
    const [isLinkEditorOpen, setIsLinkEditorOpen] = useState(initialLinkEditorOpen)
    const [linkHref, setLinkHref] = useState(currentLinkHref ?? '')
    const toolbarStyle = {
        '--markdown-notebook-format-toolbar-top': `${top}px`,
        '--markdown-notebook-format-toolbar-left': `${left}px`,
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

    return (
        <div
            className={clsx('MarkdownNotebook__format-toolbar', `MarkdownNotebook__format-toolbar--${placement}`)}
            contentEditable={false}
            style={toolbarStyle}
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
                {TEXT_BLOCK_STYLE_BUTTONS.map((button) => (
                    <LemonButton
                        key={button.label}
                        size="xsmall"
                        icon={button.icon}
                        tooltip={button.label}
                        aria-label={button.label}
                        active={selectedBlockStyle === button.style}
                        className="MarkdownNotebook__format-style-button"
                        onClick={() => setBlockStyle(selectedBlockStyle === button.style ? 'paragraph' : button.style)}
                    >
                        {button.content}
                    </LemonButton>
                ))}
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
            {showInlineActions && askAIAboutSelection ? (
                <LemonButton
                    size="xsmall"
                    icon={<IconSparkles />}
                    tooltip="Ask AI"
                    aria-label="Ask AI"
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
    codeRanges: FloatingToolbarCodeRange[]
): TextBlockStyle | null {
    if (codeRanges.length) {
        return textRanges.length ? null : 'code'
    }

    return getSelectedTextBlockStyle(textRanges)
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
