import { PluginKey } from '@tiptap/pm/state'
import { Editor, Extension, ReactRenderer } from '@tiptap/react'
import Suggestion from '@tiptap/suggestion'
import { forwardRef, useCallback, useEffect, useImperativeHandle, useState } from 'react'

import { IconColumns, IconList, IconMinus, IconQuote, IconThumbsUp } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover'

import { FormQuestionType } from '../../formTypes'
import { getDefaultQuestion, QUESTION_TYPE_REGISTRY } from '../questions/questionTypeRegistry'

export interface SlashCommandItem {
    title: string
    description: string
    icon: JSX.Element
    command: (editor: Editor) => void
    keywords?: string[]
    section: 'content' | 'form'
}

export const SLASH_COMMANDS: SlashCommandItem[] = [
    // Content blocks
    {
        title: 'Heading 1',
        description: 'Large section heading',
        icon: <span className="font-bold text-lg">H1</span>,
        keywords: ['h1', 'title', 'heading'],
        command: (editor) => editor.chain().focus().toggleHeading({ level: 1 }).run(),
        section: 'content',
    },
    {
        title: 'Heading 2',
        description: 'Medium section heading',
        icon: <span className="font-bold text-base">H2</span>,
        keywords: ['h2', 'subtitle', 'heading'],
        command: (editor) => editor.chain().focus().toggleHeading({ level: 2 }).run(),
        section: 'content',
    },
    {
        title: 'Heading 3',
        description: 'Small section heading',
        icon: <span className="font-bold text-sm">H3</span>,
        keywords: ['h3', 'heading'],
        command: (editor) => editor.chain().focus().toggleHeading({ level: 3 }).run(),
        section: 'content',
    },
    {
        title: 'Bullet list',
        description: 'Create a bullet list',
        icon: <IconList />,
        keywords: ['ul', 'unordered', 'list', 'bullet'],
        command: (editor) => editor.chain().focus().toggleBulletList().run(),
        section: 'content',
    },
    {
        title: 'Quote',
        description: 'Add a blockquote',
        icon: <IconQuote />,
        keywords: ['blockquote', 'quote'],
        command: (editor) => editor.chain().focus().toggleBlockquote().run(),
        section: 'content',
    },
    {
        title: 'Page break',
        description: 'Start a new page',
        icon: <IconColumns />,
        keywords: ['page', 'break', 'step', 'section', 'next'],
        command: (editor) => editor.chain().focus().insertPageBreak().run(),
        section: 'content',
    },
    {
        title: 'Thank you page',
        description: 'Post-submission content',
        icon: <IconThumbsUp />,
        keywords: ['thank', 'you', 'thanks', 'end', 'confirmation'],
        command: (editor) => editor.chain().focus().insertThankYouBreak().run(),
        section: 'content',
    },
    {
        title: 'Divider',
        description: 'Add a horizontal line',
        icon: <IconMinus />,
        keywords: ['hr', 'divider', 'line', 'horizontal'],
        command: (editor) => editor.chain().focus().setHorizontalRule().run(),
        section: 'content',
    },

    // Form fields — derived from the question type registry
    ...Object.values(FormQuestionType).map((type) => {
        const entry = QUESTION_TYPE_REGISTRY[type]
        return {
            title: entry.label,
            description: entry.slashDescription,
            icon: entry.icon,
            keywords: entry.keywords,
            command: (editor: Editor) => editor.chain().focus().insertFormQuestion(getDefaultQuestion(type)).run(),
            section: 'form' as const,
        }
    }),
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

const SlashCommandsList = forwardRef<SlashCommandsRef, SlashCommandsProps>(function SlashCommandsList(
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

    // Order must match the visual rendering: form fields first, then content
    const formCommands = filteredCommands.filter((c) => c.section === 'form')
    const contentCommands = filteredCommands.filter((c) => c.section === 'content')
    const orderedCommands = [...formCommands, ...contentCommands]

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
                setSelectedIndex((prev) => (prev > 0 ? prev - 1 : orderedCommands.length - 1))
                return true
            }

            if (event.key === 'ArrowDown') {
                setSelectedIndex((prev) => (prev < orderedCommands.length - 1 ? prev + 1 : 0))
                return true
            }

            if (event.key === 'Enter') {
                const item = orderedCommands[selectedIndex]
                if (item) {
                    executeCommand(item)
                }
                return true
            }

            return false
        },
        [orderedCommands, selectedIndex, executeCommand]
    )

    useImperativeHandle(ref, () => ({ onKeyDown }), [onKeyDown])

    if (orderedCommands.length === 0) {
        return (
            <div className="p-3 text-muted text-sm">
                No commands matching "<code>{query}</code>"
            </div>
        )
    }

    let flatIndex = 0

    return (
        <div className="py-1 max-h-80 overflow-y-auto min-w-64">
            {formCommands.length > 0 && (
                <>
                    <div className="px-3 py-1 text-xs font-semibold text-muted uppercase tracking-wider">
                        Form fields
                    </div>
                    {formCommands.map((item) => {
                        const currentIndex = flatIndex++
                        return (
                            <LemonButton
                                key={item.title}
                                fullWidth
                                active={currentIndex === selectedIndex}
                                onClick={() => executeCommand(item)}
                                icon={item.icon}
                                className="justify-start"
                            >
                                <div className="flex flex-col items-start">
                                    <span className="font-medium">{item.title}</span>
                                    <span className="text-xs text-muted">{item.description}</span>
                                </div>
                            </LemonButton>
                        )
                    })}
                </>
            )}
            {contentCommands.length > 0 && (
                <>
                    <div className="px-3 py-1 text-xs font-semibold text-muted uppercase tracking-wider mt-1">
                        Content
                    </div>
                    {contentCommands.map((item) => {
                        const currentIndex = flatIndex++
                        return (
                            <LemonButton
                                key={item.title}
                                fullWidth
                                active={currentIndex === selectedIndex}
                                onClick={() => executeCommand(item)}
                                icon={item.icon}
                                className="justify-start"
                            >
                                <div className="flex flex-col items-start">
                                    <span className="font-medium">{item.title}</span>
                                    <span className="text-xs text-muted">{item.description}</span>
                                </div>
                            </LemonButton>
                        )
                    })}
                </>
            )}
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
            overlay={<SlashCommandsList ref={ref} onClose={onClose} {...props} />}
            referenceElement={decorationNode}
            visible={visible}
            onClickOutside={onClose}
        >
            <span />
        </Popover>
    )
})

const SlashCommandPluginKey = new PluginKey('survey-slash-commands')

export const SlashCommandExtension = Extension.create({
    name: 'survey-slash-commands',

    addProseMirrorPlugins() {
        return [
            Suggestion({
                pluginKey: SlashCommandPluginKey,
                editor: this.editor,
                char: '/',
                startOfLine: false,
                allow: ({ state, range }) => {
                    const titleEnd = state.doc.firstChild?.nodeSize ?? 0
                    return range.from >= titleEnd
                },
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
