import { ChainedCommands, Editor, Extension, Range } from '@tiptap/core'
import Suggestion, { SuggestionKeyDownProps } from '@tiptap/suggestion'

import { FloatingMenu, ReactRenderer } from '@tiptap/react'
import { LemonButton, LemonButtonWithDropdown, LemonDivider } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { notebookLogic } from './notebookLogic'
import { IconCohort, IconPlus, IconQueryEditor, IconRecording, IconTableChart } from 'lib/lemon-ui/icons'
import { forwardRef, useCallback, useImperativeHandle, useMemo, useState } from 'react'
import { isCurrentNodeEmpty } from './utils'
import { NotebookNodeType } from '~/types'
import { examples } from '~/queries/examples'
import { Popover } from 'lib/lemon-ui/Popover'
import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import Fuse from 'fuse.js'

type SlashCommandsProps = {
    editor: Editor
    mode: 'slash' | 'add'
    query?: string
    range?: Range
    decorationNode?: any
}

type SlashCommandsRef = {
    onKeyDown: (props: SuggestionKeyDownProps) => boolean | undefined
}

type SlashCommandsItem = {
    title: string
    icon?: JSX.Element
    command: (chain: ChainedCommands) => ChainedCommands
}

const TEXT_CONTROLS: SlashCommandsItem[] = [
    {
        title: 'H1',
        command: (chain) => chain.toggleHeading({ level: 1 }),
    },
    {
        title: 'H2',
        command: (chain) => chain.toggleHeading({ level: 1 }),
    },
    {
        title: 'H3',
        command: (chain) => chain.toggleHeading({ level: 1 }),
    },
    {
        title: 'B',
        command: (chain) => chain.toggleBold(),
    },
    {
        title: 'I',
        command: (chain) => chain.toggleBold(),
    },
]

const SLASH_COMMANDS: SlashCommandsItem[] = [
    {
        title: 'HoqQL',
        icon: <IconQueryEditor />,
        command: (chain) =>
            chain.insertContent({ type: NotebookNodeType.Query, attrs: { query: examples['HogQLTable'] } }),
    },
    {
        title: 'Events',
        icon: <IconTableChart />,
        command: (chain) =>
            chain.insertContent({ type: NotebookNodeType.Query, attrs: { query: examples['EventsTableFull'] } }),
    },
    {
        title: 'Persons',
        icon: <IconCohort />,
        command: (chain) =>
            chain.insertContent({ type: NotebookNodeType.Query, attrs: { query: examples['PersonsTableFull'] } }),
    },
    {
        title: 'Session Replays',
        icon: <IconRecording />,
        command: (chain) => chain.insertContent({ type: NotebookNodeType.RecordingPlaylist, attrs: {} }),
    },
]

const SlashCommands = forwardRef<SlashCommandsRef, SlashCommandsProps>(function SlashCommands(
    { mode, editor, range = { from: 0, to: 0 }, query },
    ref
): JSX.Element | null {
    // We start with 1 because the first item is the text controls
    const [selectedIndex, setSelectedIndex] = useState(0)
    const [selectedHorizontalIndex, setSelectedHorizontalIndex] = useState(0)

    const allCommmands = [...TEXT_CONTROLS, ...SLASH_COMMANDS]

    const fuse = useMemo(() => {
        return new Fuse(allCommmands, {
            keys: ['title'],
            threshold: 0.3,
        })
    }, [allCommmands])

    const filteredCommands = useMemo(() => {
        if (!query) {
            return allCommmands
        }
        return fuse.search(query).map((result) => result.item)
    }, [query, fuse])

    const filteredSlashCommands = useMemo(() => {
        return filteredCommands.filter((item) => SLASH_COMMANDS.includes(item))
    }, [filteredCommands])

    const onPressEnter = (): void => {
        const command =
            selectedIndex === -1
                ? TEXT_CONTROLS[selectedHorizontalIndex].command
                : SLASH_COMMANDS[selectedIndex].command

        command(editor.chain().focus().deleteRange(range)).run()
    }
    const onPressUp = (): void => {
        setSelectedIndex(Math.max(selectedIndex - 1, -1))
    }
    const onPressDown = (): void => {
        setSelectedIndex(Math.min(selectedIndex + 1, SLASH_COMMANDS.length - 1))
    }

    const onPressLeft = (): void => {
        setSelectedHorizontalIndex(Math.max(selectedHorizontalIndex - 1, 0))
    }
    const onPressRight = (): void => {
        setSelectedHorizontalIndex(Math.min(selectedHorizontalIndex + 1, TEXT_CONTROLS.length - 1))
    }

    useImperativeHandle(ref, () => ({
        onKeyDown: ({ event }) => {
            const keyMappings = {
                ArrowUp: onPressUp,
                ArrowDown: onPressDown,
                ArrowLeft: onPressLeft,
                ArrowRight: onPressRight,
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
        <div className="SlashCommands space-y-px">
            <div className="flex items-center gap-1">
                {TEXT_CONTROLS.map((item, index) => (
                    <LemonButton
                        key={item.title}
                        status="primary-alt"
                        size="small"
                        active={selectedIndex === -1 && selectedHorizontalIndex === index}
                        onClick={() => item.command(editor.chain().focus().deleteRange(range)).run()}
                    >
                        {item.title}
                    </LemonButton>
                ))}
            </div>

            <LemonDivider className="my-0" />

            {filteredSlashCommands.map((item, index) => (
                <LemonButton
                    key={item.title}
                    fullWidth
                    status="stealth"
                    icon={item.icon}
                    active={index === selectedIndex}
                    onClick={() => item.command(editor.chain().focus().deleteRange(range)).run()}
                >
                    {item.title}
                </LemonButton>
            ))}

            {mode === 'add' && (
                <>
                    <LemonDivider className="my-0" />
                    <div className="text-xs text-muted-alt p-1">
                        You can trigger this menu by typing <KeyboardShortcut forwardslash />
                    </div>
                </>
            )}
        </div>
    )
})

const SlashCommandsPopover = forwardRef<SlashCommandsRef, SlashCommandsProps>(function SlashCommandsPopover(
    props: SlashCommandsProps,
    ref
): JSX.Element | null {
    return (
        <Popover
            overlay={<SlashCommands ref={ref} {...props} mode="slash" />}
            visible
            referenceElement={props.decorationNode}
        />
    )
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
                    overlay: <SlashCommands mode="add" editor={editor} range={undefined} />,
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
                            renderer.destroy()
                        },
                    }
                },
            }),
        ]
    },
})
