import { PluginKey } from '@tiptap/pm/state'
import { Editor, Extension, ReactRenderer } from '@tiptap/react'
import Suggestion from '@tiptap/suggestion'
import { forwardRef, useCallback, useEffect, useImperativeHandle, useState } from 'react'

import { IconCode, IconImage, IconList, IconMinus, IconQuote, IconVideoCamera } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover'

function IconHeading({ className }: { className?: string }): JSX.Element {
    return (
        <svg
            className={className}
            width="1em"
            height="1em"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
        >
            <path
                d="M4 12h8M4 18V6M12 18V6M17 10l3 2-3 2M17 14v4h6"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
            />
        </svg>
    )
}

function IconListNumbers(): JSX.Element {
    return (
        <svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path
                d="M10 6h11M10 12h11M10 18h11M4 6h1v4M4 10h2M4 14h1.5a.5.5 0 0 1 0 1H4h2a.5.5 0 0 1 0 1H4"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
            />
        </svg>
    )
}

export interface SlashCommandItem {
    title: string
    description: string
    icon: JSX.Element
    command: (editor: Editor) => void
    keywords?: string[]
}

const SLASH_COMMANDS: SlashCommandItem[] = [
    {
        title: 'Heading 1',
        description: 'Large section heading',
        icon: <IconHeading className="text-lg" />,
        keywords: ['h1', 'title', 'heading'],
        command: (editor) => editor.chain().focus().toggleHeading({ level: 1 }).run(),
    },
    {
        title: 'Heading 2',
        description: 'Medium section heading',
        icon: <IconHeading className="text-base" />,
        keywords: ['h2', 'subtitle', 'heading'],
        command: (editor) => editor.chain().focus().toggleHeading({ level: 2 }).run(),
    },
    {
        title: 'Heading 3',
        description: 'Small section heading',
        icon: <IconHeading className="text-sm" />,
        keywords: ['h3', 'heading'],
        command: (editor) => editor.chain().focus().toggleHeading({ level: 3 }).run(),
    },
    {
        title: 'Bullet list',
        description: 'Create a bullet list',
        icon: <IconList />,
        keywords: ['ul', 'unordered', 'list', 'bullet'],
        command: (editor) => editor.chain().focus().toggleBulletList().run(),
    },
    {
        title: 'Numbered list',
        description: 'Create a numbered list',
        icon: <IconListNumbers />,
        keywords: ['ol', 'ordered', 'list', 'number'],
        command: (editor) => editor.chain().focus().toggleOrderedList().run(),
    },
    {
        title: 'Quote',
        description: 'Add a blockquote',
        icon: <IconQuote />,
        keywords: ['blockquote', 'quote'],
        command: (editor) => editor.chain().focus().toggleBlockquote().run(),
    },
    {
        title: 'Code block',
        description: 'Add a code block',
        icon: <IconCode />,
        keywords: ['code', 'codeblock', 'pre'],
        command: (editor) => editor.chain().focus().toggleCodeBlock().run(),
    },
    {
        title: 'Divider',
        description: 'Add a horizontal line',
        icon: <IconMinus />,
        keywords: ['hr', 'divider', 'line', 'horizontal'],
        command: (editor) => editor.chain().focus().setHorizontalRule().run(),
    },
    {
        title: 'Image',
        description: 'Upload or embed an image',
        icon: <IconImage />,
        keywords: ['image', 'img', 'picture', 'photo'],
        command: (editor) => {
            const event = new CustomEvent('product-tour-editor:insert-image')
            window.dispatchEvent(event)
            editor.chain().focus().run()
        },
    },
    {
        title: 'Video embed',
        description: 'Embed YouTube, Vimeo, or Loom',
        icon: <IconVideoCamera />,
        keywords: ['video', 'youtube', 'vimeo', 'loom', 'embed'],
        command: (editor) => {
            const event = new CustomEvent('product-tour-editor:insert-video')
            window.dispatchEvent(event)
            editor.chain().focus().run()
        },
    },
]

interface SlashCommandsProps {
    editor: Editor
    range: { from: number; to: number }
    query: string
    onClose?: () => void
}

interface SlashCommandsRef {
    onKeyDown: (event: KeyboardEvent) => boolean
}

const SlashCommands = forwardRef<SlashCommandsRef, SlashCommandsProps>(function SlashCommands(
    { editor, range, query, onClose },
    ref
): JSX.Element {
    const [selectedIndex, setSelectedIndex] = useState(0)

    const filteredCommands = SLASH_COMMANDS.filter((item) => {
        if (!query) {
            return true
        }
        const searchQuery = query.toLowerCase()
        return (
            item.title.toLowerCase().includes(searchQuery) ||
            item.description.toLowerCase().includes(searchQuery) ||
            item.keywords?.some((keyword) => keyword.includes(searchQuery))
        )
    })

    useEffect(() => {
        setSelectedIndex(0)
    }, [query])

    const executeCommand = useCallback(
        (item: SlashCommandItem) => {
            editor.chain().focus().deleteRange(range).run()
            item.command(editor)
            onClose?.()
        },
        [editor, range, onClose]
    )

    const onKeyDown = useCallback(
        (event: KeyboardEvent): boolean => {
            if (event.key === 'ArrowUp') {
                setSelectedIndex((prev) => (prev > 0 ? prev - 1 : filteredCommands.length - 1))
                return true
            }

            if (event.key === 'ArrowDown') {
                setSelectedIndex((prev) => (prev < filteredCommands.length - 1 ? prev + 1 : 0))
                return true
            }

            if (event.key === 'Enter') {
                const item = filteredCommands[selectedIndex]
                if (item) {
                    executeCommand(item)
                }
                return true
            }

            return false
        },
        [filteredCommands, selectedIndex, executeCommand]
    )

    useImperativeHandle(ref, () => ({ onKeyDown }), [onKeyDown])

    if (filteredCommands.length === 0) {
        return (
            <div className="p-3 text-muted text-sm">
                No commands matching "<code>{query}</code>"
            </div>
        )
    }

    return (
        <div className="py-1 max-h-80 overflow-y-auto">
            {filteredCommands.map((item, index) => (
                <LemonButton
                    key={item.title}
                    fullWidth
                    active={index === selectedIndex}
                    onClick={() => executeCommand(item)}
                    icon={item.icon}
                    className="justify-start"
                >
                    <div className="flex flex-col items-start">
                        <span className="font-medium">{item.title}</span>
                        <span className="text-xs text-muted">{item.description}</span>
                    </div>
                </LemonButton>
            ))}
        </div>
    )
})

interface SlashCommandsPopoverProps extends SlashCommandsProps {
    visible: boolean
    decorationNode?: HTMLElement | null
}

const SlashCommandsPopover = forwardRef<SlashCommandsRef, SlashCommandsPopoverProps>(function SlashCommandsPopover(
    { visible, decorationNode, onClose, ...props },
    ref
): JSX.Element {
    return (
        <Popover
            placement="bottom-start"
            fallbackPlacements={['top-start']}
            overlay={<SlashCommands ref={ref} onClose={onClose} {...props} />}
            referenceElement={decorationNode}
            visible={visible}
            onClickOutside={onClose}
        >
            <span />
        </Popover>
    )
})

const SlashCommandPluginKey = new PluginKey('slash-commands')

export const SlashCommandExtension = Extension.create({
    name: 'slash-commands',

    addProseMirrorPlugins() {
        return [
            Suggestion({
                pluginKey: SlashCommandPluginKey,
                editor: this.editor,
                char: '/',
                startOfLine: false,
                render: () => {
                    let renderer: ReactRenderer<SlashCommandsRef>

                    return {
                        onStart: (props) => {
                            renderer = new ReactRenderer(SlashCommandsPopover, {
                                props: {
                                    ...props,
                                    visible: true,
                                },
                                editor: props.editor,
                            })
                        },

                        onUpdate(props) {
                            renderer.updateProps({
                                ...props,
                                visible: true,
                            })
                        },

                        onKeyDown(props) {
                            if (props.event.key === 'Escape') {
                                renderer.destroy()
                                return true
                            }
                            return renderer.ref?.onKeyDown(props.event) ?? false
                        },

                        onExit() {
                            renderer.destroy()
                        },
                    }
                },
            }),
        ]
    },
})
