import './MarkdownPanel.css'

import { Placeholder } from '@tiptap/extensions'
import { type Editor, EditorContent, useEditor, useEditorState } from '@tiptap/react'
import { BubbleMenu } from '@tiptap/react/menus'
import clsx from 'clsx'
import { type MutableRefObject, useEffect, useRef, useState } from 'react'

import { IconChevronDown, IconCode } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
    Input,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Separator,
    Toggle,
} from '@posthog/quill'

import {
    DEFAULT_INLINE_MARKDOWN_SLASH_COMMANDS,
    INLINE_MARKDOWN_SLASH_COMMANDS_PLUGIN_KEY,
    type InlineMarkdownSlashLinkHostRef,
    createInlineMarkdownSlashCommandsExtension,
} from 'lib/components/MarkdownEditor/inline/inlineMarkdownSlashCommands'

import type { PanelComponentProps } from '../core/panelDefinition'
import { MARKDOWN_EXTENSIONS, markdownContent, serializeMarkdown } from './markdownContent'
import type { MarkdownConfig } from './markdownSpec'

// Images only show as links (see markdownContent), and Markdown has no underline.
const SLASH_COMMANDS = DEFAULT_INLINE_MARKDOWN_SLASH_COMMANDS.filter(
    (item) => !item.isImagePick && item.title !== 'Underline'
)

/**
 * Text that edits in place: what a person types is what viewers see. The config stays Markdown, so text written
 * before this editor, or by a host that writes Markdown, opens unchanged.
 */
export function MarkdownPanel({ panel, setConfig }: PanelComponentProps<MarkdownConfig>): JSX.Element {
    const text = panel.config.text
    const editable = !!setConfig
    const dirty = useRef(false)
    const focusedOnPress = useRef(false)
    // The format menu's link button fills this in, so the `/` menu's Link opens the same box.
    const linkHost = useRef<InlineMarkdownSlashLinkHostRef | null>(null)
    const [extensions] = useState(() => [
        ...MARKDOWN_EXTENSIONS,
        Placeholder.configure({ placeholder: "Write something, or type '/' for commands" }),
        createInlineMarkdownSlashCommandsExtension(INLINE_MARKDOWN_SLASH_COMMANDS_PLUGIN_KEY, SLASH_COMMANDS, {
            slashLinkHostRef: linkHost,
        }),
    ])

    const editor = useEditor({
        extensions,
        ...markdownContent(text),
        editable,
        editorProps: {
            // A tile's text is read far more than it is edited, so a click on a link follows it. Once a person is
            // editing, a click places the cursor instead, and Cmd or Ctrl and click follows the link.
            handleDOMEvents: {
                mousedown: (view) => {
                    focusedOnPress.current = view.hasFocus()
                    return false
                },
            },
            handleClick: (_view, _pos, event) => {
                const href =
                    event.target instanceof Element ? event.target.closest('a[href]')?.getAttribute('href') : null
                if (!href || (focusedOnPress.current && !event.metaKey && !event.ctrlKey)) {
                    return false
                }
                event.preventDefault()
                window.open(href, '_blank', 'noopener,noreferrer')
                return true
            },
        },
        shouldRerenderOnTransaction: false,
        immediatelyRender: true,
        onUpdate: () => {
            dirty.current = true
        },
    })

    // Saving on blur keeps one edit session as one undo step, and leaves text that was only clicked into unchanged.
    const setConfigRef = useRef(setConfig)
    setConfigRef.current = setConfig
    useEffect(() => {
        const save = (): void => {
            if (!dirty.current) {
                return
            }
            dirty.current = false
            setConfigRef.current?.({ ...panel.config, text: serializeMarkdown(editor) })
        }
        editor.on('blur', save)
        return () => {
            editor.off('blur', save)
            save()
        }
    }, [editor, panel.config])

    useEffect(() => {
        editor.setEditable(editable)
    }, [editor, editable])

    // An undo, or another tab showing the same panel, changes the text from outside the editor.
    useEffect(() => {
        if (editor.isFocused || dirty.current || serializeMarkdown(editor) === text) {
            return
        }
        const { content, contentType } = markdownContent(text)
        editor.commands.setContent(content, { contentType, emitUpdate: false })
    }, [editor, text])

    return (
        <>
            {editable && <FormatMenu editor={editor} linkHost={linkHost} />}
            <EditorContent
                editor={editor}
                className={clsx(
                    'TileGrid__text dash-MarkdownPanel text-sm',
                    editable && 'dash-MarkdownPanel--editable'
                )}
            />
        </>
    )
}

interface BlockType {
    label: string
    isActive: (editor: Editor) => boolean
    /** Clears the current block first, so a list or quote turns into this rather than nesting it. */
    apply: (editor: Editor) => void
}

const BLOCK_TYPES: BlockType[] = [
    {
        label: 'Plain text',
        isActive: (editor) =>
            editor.isActive('paragraph') &&
            !editor.isActive('bulletList') &&
            !editor.isActive('orderedList') &&
            !editor.isActive('taskList') &&
            !editor.isActive('blockquote'),
        apply: (editor) => editor.chain().focus().clearNodes().run(),
    },
    ...([1, 2, 3] as const).map(
        (level): BlockType => ({
            label: `Heading ${level}`,
            isActive: (editor) => editor.isActive('heading', { level }),
            apply: (editor) => editor.chain().focus().clearNodes().setHeading({ level }).run(),
        })
    ),
    {
        label: 'Bullet list',
        isActive: (editor) => editor.isActive('bulletList'),
        apply: (editor) => editor.chain().focus().clearNodes().toggleBulletList().run(),
    },
    {
        label: 'Numbered list',
        isActive: (editor) => editor.isActive('orderedList'),
        apply: (editor) => editor.chain().focus().clearNodes().toggleOrderedList().run(),
    },
    {
        label: 'Task list',
        isActive: (editor) => editor.isActive('taskList'),
        apply: (editor) => editor.chain().focus().clearNodes().toggleTaskList().run(),
    },
    {
        label: 'Blockquote',
        isActive: (editor) => editor.isActive('blockquote'),
        apply: (editor) => editor.chain().focus().clearNodes().setBlockquote().run(),
    },
    {
        label: 'Code block',
        isActive: (editor) => editor.isActive('codeBlock'),
        apply: (editor) => editor.chain().focus().clearNodes().setCodeBlock().run(),
    },
]

/**
 * The menu over selected text: what the block is, and the marks people reach for most. Everything else, such as
 * dividers, is in the `/` menu.
 */
function FormatMenu({
    editor,
    linkHost,
}: {
    editor: Editor
    linkHost: MutableRefObject<InlineMarkdownSlashLinkHostRef | null>
}): JSX.Element {
    // The block menu mounts inside the toolbar, so the toolbar doesn't read opening it as the editor losing focus.
    const [menuElement, setMenuElement] = useState<HTMLDivElement | null>(null)
    const [blockMenuOpen, setBlockMenuOpen] = useState(false)
    const active = useEditorState({
        editor,
        selector: ({ editor }) => ({
            block: BLOCK_TYPES.find((type) => type.isActive(editor))?.label ?? 'Plain text',
            bold: editor.isActive('bold'),
            italic: editor.isActive('italic'),
            strike: editor.isActive('strike'),
            code: editor.isActive('code'),
            link: editor.isActive('link'),
        }),
    })

    const marks = [
        { label: 'Bold', icon: <b>B</b>, on: active.bold, toggle: () => editor.chain().focus().toggleBold().run() },
        {
            label: 'Italic',
            icon: <i>I</i>,
            on: active.italic,
            toggle: () => editor.chain().focus().toggleItalic().run(),
        },
        {
            label: 'Strikethrough',
            icon: <s>S</s>,
            on: active.strike,
            toggle: () => editor.chain().focus().toggleStrike().run(),
        },
        {
            label: 'Inline code',
            icon: <IconCode />,
            on: active.code,
            toggle: () => editor.chain().focus().toggleCode().run(),
        },
    ]

    return (
        <BubbleMenu
            ref={setMenuElement}
            editor={editor}
            className="dash-MarkdownPanel__menu"
            // Inside the tile, the part of the menu above a tile near the top sits under the tile above it.
            appendTo={() => document.body}
            options={{ strategy: 'fixed' }}
        >
            {/* Not modal: a modal menu blocks the page behind an overlay, and the editor needs its selection back. */}
            <DropdownMenu open={blockMenuOpen} onOpenChange={setBlockMenuOpen} modal={false}>
                <DropdownMenuTrigger render={<Button size="sm" />}>
                    {active.block}
                    <IconChevronDown />
                </DropdownMenuTrigger>
                <DropdownMenuContent container={menuElement}>
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>Turn into</DropdownMenuLabel>
                        <DropdownMenuRadioGroup
                            value={active.block}
                            onValueChange={(label) => {
                                BLOCK_TYPES.find((type) => type.label === label)?.apply(editor)
                                setBlockMenuOpen(false)
                            }}
                        >
                            {BLOCK_TYPES.map((type) => (
                                <DropdownMenuRadioItem key={type.label} value={type.label}>
                                    {type.label}
                                </DropdownMenuRadioItem>
                            ))}
                        </DropdownMenuRadioGroup>
                    </DropdownMenuGroup>
                </DropdownMenuContent>
            </DropdownMenu>
            <Separator orientation="vertical" />
            {marks.map((mark) => (
                <Toggle
                    key={mark.label}
                    size="icon"
                    aria-label={mark.label}
                    pressed={mark.on}
                    onPressedChange={mark.toggle}
                    // Keeps the selection in the editor while the button is pressed.
                    onMouseDown={(event) => event.preventDefault()}
                >
                    {mark.icon}
                </Toggle>
            ))}
            <LinkButton editor={editor} active={active.link} container={menuElement} linkHost={linkHost} />
        </BubbleMenu>
    )
}

// @posthog/icons has no link icon.
function IconLink(): JSX.Element {
    return (
        <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
            <path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7" strokeLinecap="round" />
            <path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7" strokeLinecap="round" />
        </svg>
    )
}

function linkHref(editor: Editor): string {
    return (editor.getAttributes('link').href as string | undefined) ?? ''
}

/** Adds, changes or removes the link on the selected text. An empty address removes it. */
function LinkButton({
    editor,
    active,
    container,
    linkHost,
}: {
    editor: Editor
    active: boolean
    container: HTMLElement | null
    linkHost: MutableRefObject<InlineMarkdownSlashLinkHostRef | null>
}): JSX.Element {
    const [open, setOpen] = useState(false)
    const [href, setHref] = useState('')
    useEffect(() => {
        linkHost.current = {
            // The menu only shows over selected text, so with nothing selected the link gets a word to sit on.
            openLinkPopover: () => {
                const { empty, from } = editor.state.selection
                if (empty) {
                    editor
                        .chain()
                        .focus()
                        .insertContent('link')
                        .setTextSelection({ from, to: from + 4 })
                        .run()
                }
                setHref(linkHref(editor))
                setOpen(true)
            },
        }
        return () => {
            linkHost.current = null
        }
    }, [editor, linkHost])
    const apply = (): void => {
        const url = href.trim()
        const chain = editor.chain().focus().extendMarkRange('link')
        if (url) {
            chain.setLink({ href: /^([a-z][a-z0-9+.-]*:|\/|#)/i.test(url) ? url : `https://${url}` }).run()
        } else {
            chain.unsetLink().run()
        }
        setOpen(false)
    }
    return (
        <Popover
            open={open}
            onOpenChange={(next) => {
                setOpen(next)
                if (next) {
                    setHref(linkHref(editor))
                }
            }}
        >
            <PopoverTrigger
                render={
                    <Toggle
                        size="icon"
                        aria-label="Link"
                        pressed={active}
                        onMouseDown={(event) => event.preventDefault()}
                    />
                }
            >
                <IconLink />
            </PopoverTrigger>
            <PopoverContent container={container} className="w-72 p-2">
                <form
                    onSubmit={(event) => {
                        event.preventDefault()
                        apply()
                    }}
                >
                    <Input
                        autoFocus
                        size="sm"
                        placeholder="Paste a link"
                        value={href}
                        onChange={(event) => setHref(event.target.value)}
                    />
                </form>
            </PopoverContent>
        </Popover>
    )
}
