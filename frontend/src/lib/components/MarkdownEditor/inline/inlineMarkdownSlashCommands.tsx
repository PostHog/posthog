import { PluginKey } from '@tiptap/pm/state'
import type { EditorView } from '@tiptap/pm/view'
import { Editor, Extension, ReactRenderer } from '@tiptap/react'
import Suggestion, { exitSuggestion } from '@tiptap/suggestion'
import { useValues } from 'kea'
import {
    forwardRef,
    useCallback,
    useEffect,
    useImperativeHandle,
    useLayoutEffect,
    useRef,
    useState,
    type MutableRefObject,
} from 'react'

import { IconCode, IconImage, IconList, IconMinus, IconQuote } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { IconBold, IconItalic, IconLink, IconTextSize } from 'lib/lemon-ui/icons'
import { Popover } from 'lib/lemon-ui/Popover'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

/** Plugin key for {@link createInlineMarkdownSlashCommandsExtension} (use for `exitSuggestion` / debugging). */
export const INLINE_MARKDOWN_SLASH_COMMANDS_PLUGIN_KEY = new PluginKey('inlineRichMarkdownSlashCommands')

export type InlineMarkdownSlashCommandItem = {
    title: string
    description: string
    icon: JSX.Element
    command: (editor: Editor) => void
    keywords?: string[]
    /** Section header in the menu (e.g. "Style", "Insert") */
    section?: string
    /**
     * Opens the image file picker via {@link InlineMarkdownSlashImageHostRef}; `command` is not invoked.
     * Omit from custom `slashCommands` if uploads are not available.
     */
    isImagePick?: boolean
    /**
     * Opens the link URL popover via {@link InlineMarkdownSlashLinkHostRef} (inline editor); `command` is not invoked.
     */
    isLinkPopover?: boolean
}

/** Mutable ref the inline editor sets each render; passed into `createInlineMarkdownSlashCommandsExtension`. */
export type InlineMarkdownSlashImageHostRef = {
    pick: () => void
    showSlashImageUpload: boolean
}

/** Mutable ref the inline editor sets each render; opens the same link popover as the bubble toolbar. */
export type InlineMarkdownSlashLinkHostRef = {
    openLinkPopover: () => void
}

function HeadingIcon({ level }: { level: 1 | 2 | 3 }): JSX.Element {
    return (
        <span className="text-xs font-bold text-secondary tabular-nums" aria-hidden>
            H{level}
        </span>
    )
}

/** Fixed slot so every row's glyph lines up with LemonButton's label column */
function SlashCommandIconSlot({ children }: { children: JSX.Element }): JSX.Element {
    return (
        <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center text-secondary [&_svg]:size-[1.125rem]">
            {children}
        </span>
    )
}

const STYLE_SECTION = 'Style'
const INSERT_SECTION = 'Insert'

/** Default `/` menu: same capabilities as the markdown bubble / rich toolbars (RichMarkdownEditorFormatControls). */
export const DEFAULT_INLINE_MARKDOWN_SLASH_COMMANDS: InlineMarkdownSlashCommandItem[] = [
    {
        title: 'Plain text',
        description: 'Normal paragraph',
        icon: <IconTextSize />,
        keywords: ['paragraph', 'p', 'plain', 'text'],
        section: STYLE_SECTION,
        command: (editor) => editor.chain().focus().setParagraph().run(),
    },
    {
        title: 'Heading 1',
        description: 'Large section heading',
        icon: <HeadingIcon level={1} />,
        keywords: ['h1', 'title', 'heading'],
        section: STYLE_SECTION,
        command: (editor) => editor.chain().focus().toggleHeading({ level: 1 }).run(),
    },
    {
        title: 'Heading 2',
        description: 'Medium section heading',
        icon: <HeadingIcon level={2} />,
        keywords: ['h2', 'subtitle', 'heading'],
        section: STYLE_SECTION,
        command: (editor) => editor.chain().focus().toggleHeading({ level: 2 }).run(),
    },
    {
        title: 'Heading 3',
        description: 'Small section heading',
        icon: <HeadingIcon level={3} />,
        keywords: ['h3', 'heading'],
        section: STYLE_SECTION,
        command: (editor) => editor.chain().focus().toggleHeading({ level: 3 }).run(),
    },
    {
        title: 'Bold',
        description: 'Strong emphasis',
        icon: <IconBold />,
        keywords: ['strong', 'b'],
        section: STYLE_SECTION,
        command: (editor) => editor.chain().focus().toggleBold().run(),
    },
    {
        title: 'Italic',
        description: 'Emphasis',
        icon: <IconItalic />,
        keywords: ['emphasis', 'i'],
        section: STYLE_SECTION,
        command: (editor) => editor.chain().focus().toggleItalic().run(),
    },
    {
        title: 'Underline',
        description: 'Underline text',
        icon: (
            <span className="text-sm font-semibold underline leading-none" aria-hidden>
                U
            </span>
        ),
        keywords: ['u'],
        section: STYLE_SECTION,
        command: (editor) => editor.chain().focus().toggleUnderline().run(),
    },
    {
        title: 'Strikethrough',
        description: 'Cross out text',
        icon: (
            <span className="text-sm font-semibold line-through leading-none" aria-hidden>
                S
            </span>
        ),
        keywords: ['strike', 'strikethrough', 'del', 'delete'],
        section: STYLE_SECTION,
        command: (editor) => editor.chain().focus().toggleStrike().run(),
    },
    {
        title: 'Inline code',
        description: 'Monospace inline snippet',
        icon: <IconCode />,
        keywords: ['code', 'tick'],
        section: STYLE_SECTION,
        command: (editor) => editor.chain().focus().toggleCode().run(),
    },
    {
        title: 'Blockquote',
        description: 'Quoted passage',
        icon: <IconQuote />,
        keywords: ['blockquote', 'quote'],
        section: STYLE_SECTION,
        command: (editor) => editor.chain().focus().toggleBlockquote().run(),
    },
    {
        title: 'Code block',
        description: 'Fenced code block',
        icon: <IconCode />,
        keywords: ['codeblock', 'pre'],
        section: INSERT_SECTION,
        command: (editor) => editor.chain().focus().toggleCodeBlock().run(),
    },
    {
        title: 'Horizontal divider',
        description: 'Horizontal rule between sections',
        icon: <IconMinus />,
        keywords: ['hr', 'divider', 'line', 'horizontal', 'rule', 'separator'],
        section: INSERT_SECTION,
        command: (editor) => editor.chain().focus().setHorizontalRule().run(),
    },
    {
        title: 'Bullet list',
        description: 'Unordered list',
        icon: <IconList />,
        keywords: ['ul', 'unordered', 'list', 'bullet'],
        section: INSERT_SECTION,
        command: (editor) => editor.chain().focus().toggleBulletList().run(),
    },
    {
        title: 'Numbered list',
        description: 'Ordered list',
        icon: (
            <span className="text-xs font-semibold tabular-nums text-secondary leading-none" aria-hidden>
                1.
            </span>
        ),
        keywords: ['ol', 'ordered', 'list', 'number'],
        section: INSERT_SECTION,
        command: (editor) => editor.chain().focus().toggleOrderedList().run(),
    },
    {
        title: 'Task list',
        description: 'Checklist',
        icon: (
            <span className="text-xs leading-none tabular-nums" aria-hidden>
                [ ]
            </span>
        ),
        keywords: ['todo', 'task', 'checkbox', 'checklist'],
        section: INSERT_SECTION,
        command: (editor) => editor.chain().focus().toggleTaskList().run(),
    },
    {
        title: 'Link',
        description: 'Add or edit a link',
        icon: <IconLink />,
        keywords: ['url', 'href', 'hyperlink'],
        section: INSERT_SECTION,
        isLinkPopover: true,
        command: () => {},
    },
    {
        title: 'Image',
        description: 'Upload an image (object storage required)',
        icon: <IconImage />,
        keywords: ['img', 'picture', 'photo', 'upload'],
        section: INSERT_SECTION,
        isImagePick: true,
        command: () => {},
    },
]

type InlineMarkdownSlashMenuProps = {
    editor: Editor
    range: { from: number; to: number }
    query: string
    onClose?: () => void
    commands: InlineMarkdownSlashCommandItem[]
    slashImageHostRef?: MutableRefObject<InlineMarkdownSlashImageHostRef | null>
    slashLinkHostRef?: MutableRefObject<InlineMarkdownSlashLinkHostRef | null>
}

type InlineMarkdownSlashMenuRef = {
    onKeyDown: (event: KeyboardEvent) => boolean
}

const SECTION_ORDER = [STYLE_SECTION, INSERT_SECTION]

function sectionRank(section: string): number {
    const idx = SECTION_ORDER.indexOf(section)
    return idx === -1 ? SECTION_ORDER.length + section.charCodeAt(0) : idx
}

/** Exported for tests; production uses this via {@link createInlineMarkdownSlashCommandsExtension}. */
export const InlineMarkdownSlashMenu = forwardRef<InlineMarkdownSlashMenuRef, InlineMarkdownSlashMenuProps>(
    function InlineMarkdownSlashMenu(
        { editor, range, query, onClose, commands, slashImageHostRef, slashLinkHostRef },
        ref
    ): JSX.Element {
        const [selectedFlatIndex, setSelectedFlatIndex] = useState(0)
        const activeItemRef = useRef<HTMLButtonElement | null>(null)
        const { objectStorageAvailable } = useValues(preflightLogic)

        // Compute each render (not memoized on ref identity) so `slashImageHostRef.current.showSlashImageUpload`
        // stays in sync whenever this menu re-renders (e.g. suggestion onUpdate).
        const visibleCommands = commands.filter(
            (item) =>
                !item.isImagePick || (slashImageHostRef != null && slashImageHostRef.current?.showSlashImageUpload)
        )
        const filteredCommands = !query
            ? visibleCommands
            : (() => {
                  const searchQuery = query.toLowerCase()
                  return visibleCommands.filter((item) => {
                      return (
                          item.title.toLowerCase().includes(searchQuery) ||
                          item.description.toLowerCase().includes(searchQuery) ||
                          item.keywords?.some((keyword) => keyword.includes(searchQuery))
                      )
                  })
              })()

        const grouped = (() => {
            const map = new Map<string, InlineMarkdownSlashCommandItem[]>()
            for (const item of filteredCommands) {
                const section = item.section ?? 'Commands'
                const list = map.get(section) ?? []
                list.push(item)
                map.set(section, list)
            }
            return [...map.entries()].sort((a, b) => {
                const ar = sectionRank(a[0])
                const br = sectionRank(b[0])
                if (ar !== br) {
                    return ar - br
                }
                return a[0].localeCompare(b[0])
            })
        })()

        const flatItems = grouped.flatMap(([, items]) => items)

        useEffect(() => {
            setSelectedFlatIndex(0)
        }, [query])

        useEffect(() => {
            setSelectedFlatIndex((i) => Math.min(i, Math.max(flatItems.length - 1, 0)))
        }, [flatItems.length])

        useLayoutEffect(() => {
            if (filteredCommands.length === 0) {
                return
            }
            activeItemRef.current?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
        }, [selectedFlatIndex, filteredCommands.length, grouped])

        const applySlashItem = useCallback(
            (item: InlineMarkdownSlashCommandItem) => {
                if (item.isImagePick) {
                    if (!objectStorageAvailable || slashImageHostRef?.current?.showSlashImageUpload === false) {
                        return
                    }
                    editor.chain().focus().deleteRange(range).run()
                    onClose?.()
                    requestAnimationFrame(() => {
                        slashImageHostRef?.current?.pick()
                    })
                    return
                }
                if (item.isLinkPopover) {
                    editor.chain().focus().deleteRange(range).run()
                    onClose?.()
                    requestAnimationFrame(() => {
                        slashLinkHostRef?.current?.openLinkPopover()
                    })
                    return
                }
                editor.chain().focus().deleteRange(range).run()
                item.command(editor)
                onClose?.()
            },
            [editor, objectStorageAvailable, onClose, range, slashImageHostRef, slashLinkHostRef]
        )

        const onKeyDown = useCallback(
            (event: KeyboardEvent): boolean => {
                if (event.key === 'ArrowUp') {
                    setSelectedFlatIndex((prev) => (prev > 0 ? prev - 1 : Math.max(flatItems.length - 1, 0)))
                    return true
                }

                if (event.key === 'ArrowDown') {
                    setSelectedFlatIndex((prev) => (prev < flatItems.length - 1 ? prev + 1 : 0))
                    return true
                }

                if (event.key === 'Enter') {
                    const item = flatItems[selectedFlatIndex]
                    if (item) {
                        applySlashItem(item)
                    }
                    return true
                }

                return false
            },
            [flatItems, selectedFlatIndex, applySlashItem]
        )

        useImperativeHandle(ref, () => ({ onKeyDown }), [onKeyDown])

        const listBody =
            filteredCommands.length === 0 ? (
                <div className="p-3 text-muted text-sm">
                    No commands matching "<code>{query}</code>"
                </div>
            ) : (
                (() => {
                    let runningIndex = 0
                    return (
                        <div className="py-1 max-h-72 overflow-y-auto min-w-72">
                            {grouped.map(([section, items], groupIndex) => (
                                <div key={section}>
                                    {groupIndex > 0 && <LemonDivider className="my-1" />}
                                    <div className="px-2 pt-1 pb-0.5 text-xxs font-semibold uppercase tracking-wide text-muted">
                                        {section}
                                    </div>
                                    {items.map((item) => {
                                        const index = runningIndex++
                                        const imageDisabledReason =
                                            item.isImagePick && !objectStorageAvailable
                                                ? 'Enable object storage to upload images'
                                                : undefined
                                        return (
                                            <LemonButton
                                                key={`${section}-${item.title}`}
                                                ref={index === selectedFlatIndex ? activeItemRef : undefined}
                                                fullWidth
                                                active={index === selectedFlatIndex}
                                                disabledReason={imageDisabledReason}
                                                onClick={() => applySlashItem(item)}
                                                icon={<SlashCommandIconSlot>{item.icon}</SlashCommandIconSlot>}
                                                className="justify-start"
                                            >
                                                <div className="flex flex-col items-start">
                                                    <span className="font-medium">{item.title}</span>
                                                    <span className="text-xs text-muted">{item.description}</span>
                                                </div>
                                            </LemonButton>
                                        )
                                    })}
                                </div>
                            ))}
                        </div>
                    )
                })()
            )

        return (
            <div
                className="rounded border border-primary bg-surface-primary shadow-lg overflow-hidden"
                data-attr="inline-markdown-slash-menu"
            >
                <div className="flex items-center gap-1 px-2 py-1.5 border-b border-primary">
                    <span className="text-tertiary select-none font-medium">/</span>
                    <span className="text-sm text-secondary truncate min-h-[1.25rem] flex-1">
                        {query ? query : <span className="text-muted">Filter…</span>}
                    </span>
                </div>
                {listBody}
            </div>
        )
    }
)

type InlineMarkdownSlashMenuPopoverProps = InlineMarkdownSlashMenuProps & {
    visible: boolean
    decorationNode?: HTMLElement | null
    commands: InlineMarkdownSlashCommandItem[]
}

const InlineMarkdownSlashMenuPopover = forwardRef<InlineMarkdownSlashMenuRef, InlineMarkdownSlashMenuPopoverProps>(
    function InlineMarkdownSlashMenuPopover(
        { visible, decorationNode, onClose, commands, ...props },
        ref
    ): JSX.Element {
        return (
            <Popover
                placement="bottom-start"
                fallbackPlacements={['top-start']}
                padded={false}
                overlay={<InlineMarkdownSlashMenu ref={ref} commands={commands} onClose={onClose} {...props} />}
                referenceElement={decorationNode != null ? (decorationNode as HTMLElement) : null}
                visible={visible}
                onClickOutside={onClose}
            >
                <span />
            </Popover>
        )
    }
)

export type CreateInlineMarkdownSlashCommandsExtensionOptions = {
    /** When set, **Image** slash item opens this picker after closing the menu. */
    slashImageHostRef?: MutableRefObject<InlineMarkdownSlashImageHostRef | null>
    /** When set, **Link** slash item opens the same link popover as the bubble toolbar. */
    slashLinkHostRef?: MutableRefObject<InlineMarkdownSlashLinkHostRef | null>
}

export function createInlineMarkdownSlashCommandsExtension(
    pluginKey: PluginKey,
    commands: InlineMarkdownSlashCommandItem[] = DEFAULT_INLINE_MARKDOWN_SLASH_COMMANDS,
    options?: CreateInlineMarkdownSlashCommandsExtensionOptions
): Extension {
    const slashImageHostRef = options?.slashImageHostRef
    const slashLinkHostRef = options?.slashLinkHostRef

    return Extension.create({
        name: 'inlineMarkdownSlashCommands',

        addProseMirrorPlugins() {
            return [
                Suggestion({
                    pluginKey,
                    editor: this.editor,
                    char: '/',
                    startOfLine: false,
                    render: () => {
                        let renderer: ReactRenderer<InlineMarkdownSlashMenuRef> | null = null

                        const dismiss = (view: EditorView): void => {
                            exitSuggestion(view, pluginKey)
                            renderer?.destroy()
                            renderer = null
                        }

                        return {
                            onStart: (props) => {
                                const view = props.editor.view
                                renderer = new ReactRenderer(InlineMarkdownSlashMenuPopover, {
                                    props: {
                                        ...props,
                                        commands,
                                        visible: true,
                                        onClose: () => dismiss(view),
                                        slashImageHostRef,
                                        slashLinkHostRef,
                                    },
                                    editor: props.editor,
                                })
                            },

                            onUpdate(props) {
                                if (!renderer) {
                                    return
                                }
                                const view = props.editor.view
                                renderer.updateProps({
                                    ...props,
                                    commands,
                                    visible: true,
                                    onClose: () => dismiss(view),
                                    slashImageHostRef,
                                    slashLinkHostRef,
                                })

                                if (!props.clientRect) {
                                    return
                                }
                            },

                            onKeyDown(props) {
                                if (!renderer) {
                                    return false
                                }
                                if (props.event.key === 'Escape') {
                                    dismiss(props.view)
                                    return true
                                }
                                return renderer.ref?.onKeyDown(props.event) ?? false
                            },

                            onExit() {
                                renderer?.destroy()
                                renderer = null
                            },
                        }
                    },
                }),
            ]
        },
    })
}
