import { Editor, Extension } from '@tiptap/core'
import Suggestion, { SuggestionKeyDownProps } from '@tiptap/suggestion'

import { FloatingMenu, ReactRenderer } from '@tiptap/react'
import { LemonButton, LemonButtonWithDropdown } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { notebookLogic } from './notebookLogic'
import { IconCohort, IconPlus, IconQueryEditor, IconRecording, IconTableChart } from 'lib/lemon-ui/icons'
import { forwardRef, useCallback, useImperativeHandle, useState } from 'react'
import { isCurrentNodeEmpty } from './utils'
import { NotebookNodeType } from '~/types'
import { examples } from '~/queries/examples'
import { Popover } from 'lib/lemon-ui/Popover'

type SlashCommandsProps = {
    editor?: any
    range?: any
    command?: any
    onKeyDown?: () => void
    decorationNode?: any
}

type SlashCommandsRef = {
    onKeyDown: (props: SuggestionKeyDownProps) => boolean | undefined
}

type SlashCommandsItem = {
    title: string
    icon?: JSX.Element
    command: (props: { editor: Editor; insertPostHogNode: (node: NotebookNodeType, properties?: any) => void }) => void
}

const TEXT_CONTROLS: SlashCommandsItem[] = [
    {
        title: 'H1',
        command: ({ editor }) => editor.chain().focus().toggleHeading({ level: 1 }).run(),
    },
    {
        title: 'H2',
        command: ({ editor }) => editor.chain().focus().toggleHeading({ level: 1 }).run(),
    },
    {
        title: 'H3',
        command: ({ editor }) => editor.chain().focus().toggleHeading({ level: 1 }).run(),
    },
    {
        title: 'B',
        command: ({ editor }) => editor.chain().focus().toggleBold().run(),
    },
    {
        title: 'I',
        command: ({ editor }) => editor.chain().focus().toggleBold().run(),
    },
]

const SLASH_COMMANDS: SlashCommandsItem[] = [
    {
        title: 'HoqQL',
        icon: <IconQueryEditor />,
        command: ({ editor }) =>
            editor
                .chain()
                .focus()
                .insertContent({ type: NotebookNodeType.Query, attrs: { query: examples['HogQLTable'] } })
                .run(),
    },
    {
        title: 'Events',
        icon: <IconTableChart />,
        command: ({ editor }) =>
            editor
                .chain()
                .focus()
                .insertContent({ type: NotebookNodeType.Query, attrs: { query: examples['EventsTableFull'] } })
                .run(),
    },
    {
        title: 'Persons',
        icon: <IconCohort />,
        command: ({ editor }) =>
            editor
                .chain()
                .focus()
                .insertContent({ type: NotebookNodeType.Query, attrs: { query: examples['PersonsTableFull'] } })
                .run(),
    },
    {
        title: 'Session Replays',
        icon: <IconRecording />,
        command: ({ editor }) =>
            editor.chain().focus().insertContent({ type: NotebookNodeType.RecordingPlaylist, attrs: {} }).run(),
    },
]

const SlashCommands = forwardRef<SlashCommandsRef, SlashCommandsProps>(function SlashCommands(
    props,
    ref
): JSX.Element | null {
    const { editor } = useValues(notebookLogic)
    const { insertPostHogNode } = useActions(notebookLogic)

    const [selectedIndex, setSelectedIndex] = useState(0)

    // const selectItem = (index) => {
    //     const item = props.items[index]

    //     if (item) {
    //         props.command({ id: item })
    //     }
    // }

    // const upHandler = () => {
    //     setSelectedIndex((selectedIndex + props.items.length - 1) % props.items.length)
    // }

    // const downHandler = () => {
    //     setSelectedIndex((selectedIndex + 1) % props.items.length)
    // }

    // const enterHandler = () => {
    //     selectItem(selectedIndex)
    // }

    // useEffect(() => setSelectedIndex(0), [props.items])

    const onPressEnter = () => {}
    const onPressUp = () => {}
    const onPressDown = () => {}

    useImperativeHandle(ref, () => ({
        onKeyDown: ({ event }) => {
            const keyMappings = {
                ArrowUp: onPressUp,
                ArrowDown: onPressDown,
                Enter: onPressEnter,
            }

            if (keyMappings[event.key]) {
                keyMappings[event.key]()
                return true
            }

            return false
        },
    }))

    if (!editor) {
        return null
    }

    return (
        <div className="SlashCommands">
            <div className="flex items-center gap-1 border-b pb-1">
                {TEXT_CONTROLS.map((item) => (
                    <LemonButton
                        key={item.title}
                        status="primary-alt"
                        size="small"
                        onClick={() => item.command({ editor, insertPostHogNode })}
                    >
                        {item.title}
                    </LemonButton>
                ))}
            </div>

            {SLASH_COMMANDS.map((item) => (
                <LemonButton
                    key={item.title}
                    fullWidth
                    status="stealth"
                    icon={item.icon}
                    onClick={() => item.command({ editor, insertPostHogNode })}
                >
                    {item.title}
                </LemonButton>
            ))}
        </div>
    )
})

const SlashCommandsPopover = forwardRef<SlashCommandsRef, SlashCommandsProps>(function SlashCommandsPopover(
    props: SlashCommandsProps,
    ref
): JSX.Element | null {
    return <Popover overlay={<SlashCommands ref={ref} />} visible referenceElement={props.decorationNode} />
})

export function FloatingSlashCommands(): JSX.Element | null {
    const { editor } = useValues(notebookLogic)

    const shouldShow = useCallback((): boolean => {
        if (!editor) {
            return false
        }
        if (editor.view.hasFocus() && editor.isEditable && editor.isActive('paragraph') && isCurrentNodeEmpty(editor)) {
            return true
        }

        return false
    }, [editor])

    return editor ? (
        <FloatingMenu
            editor={editor}
            tippyOptions={{ duration: 100, placement: 'left' }}
            className="NotebookFloatingButton"
            shouldShow={shouldShow}
        >
            <LemonButtonWithDropdown
                size="small"
                icon={<IconPlus />}
                dropdown={{
                    overlay: <SlashCommands />,
                    placement: 'right-start',
                    fallbackPlacements: ['left-start'],
                    actionable: true,
                    closeParentPopoverOnClickInside: true,
                }}
            />
        </FloatingMenu>
    ) : null
}

export const SlashCommandsExtension = Extension.create({
    name: 'commands',

    addProseMirrorPlugins() {
        return [
            Suggestion({
                editor: this.editor,
                char: '/',
                startOfLine: true,
                command: ({ editor, range, props }) => {
                    console.log('COMMAND', props, props.command)
                    props.command({ editor, range })
                },
                items: ({ query }) => {
                    return SLASH_COMMANDS.filter((item) => item.title.toLowerCase().startsWith(query.toLowerCase()))
                },

                render: () => {
                    let renderer: ReactRenderer<SlashCommandsRef>

                    return {
                        onStart: (props) => {
                            renderer = new ReactRenderer(SlashCommandsPopover, {
                                props,
                                editor: props.editor,
                            })
                        },

                        onUpdate(props) {
                            renderer.updateProps(props)

                            if (!props.clientRect) {
                                return
                            }
                        },

                        onKeyDown(props) {
                            if (props.event.key === 'Escape') {
                                renderer.destroy()
                                return true
                            }
                            return renderer.ref?.onKeyDown(props) ?? false
                        },

                        onExit() {
                            // popup[0].destroy()
                            renderer.destroy()
                        },
                    }
                },
            }),
        ]
    },
})
