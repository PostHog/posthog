import { Extension } from '@tiptap/core'
import Suggestion from '@tiptap/suggestion'

import { ReactRenderer } from '@tiptap/react'
import { LemonButton, LemonDivider, lemonToast } from '@posthog/lemon-ui'
import {
    IconCohort,
    IconFunnelHorizontal,
    IconQueryEditor,
    IconRecording,
    IconTableChart,
    IconTrendUp,
    IconUploadFile,
} from 'lib/lemon-ui/icons'
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useState } from 'react'
import { EditorCommands, EditorRange } from './utils'
import { NotebookNodeType } from '~/types'
import { examples } from '~/queries/examples'
import { Popover } from 'lib/lemon-ui/Popover'
import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import Fuse from 'fuse.js'
import { useValues } from 'kea'
import { notebookLogic } from './notebookLogic'
import { selectFile } from '../Nodes/utils'

type SlashCommandsProps = {
    mode: 'slash' | 'add'
    query?: string
    range?: EditorRange
    decorationNode?: any
}

type SlashCommandsRef = {
    onKeyDown: (event: KeyboardEvent) => boolean
}

type SlashCommandsItem = {
    title: string
    search?: string
    icon?: JSX.Element
    command: (chain: EditorCommands) => EditorCommands | Promise<EditorCommands>
}

const QUERY_FUNNEL = {
    kind: 'InsightVizNode',
    source: {
        kind: 'FunnelsQuery',
        filterTestAccounts: true,
        dateRange: {
            date_from: '-7d',
        },
        series: [
            {
                kind: 'EventsNode',
                event: '$pageview',
                custom_name: 'First page view',
                math: 'total',
            },
            {
                kind: 'EventsNode',
                event: '$pageview',
                custom_name: 'Second page view',
                math: 'total',
            },
            {
                kind: 'EventsNode',
                event: '$pageview',
                custom_name: 'Third page view',
                math: 'total',
            },
        ],
        breakdown: {
            breakdown_type: 'event',
            breakdown: '$browser',
        },
        funnelsFilter: {
            funnel_viz_type: 'steps',
            layout: 'horizontal',
        },
    },
    full: true,
}

const QUERY_TREND = {
    kind: 'InsightVizNode',
    source: {
        kind: 'TrendsQuery',
        series: [
            {
                kind: 'EventsNode',
                name: '$pageview',
                event: '$pageview',
                math: 'total',
            },
        ],
        trendsFilter: {},
    },
    full: true,
}

const TEXT_CONTROLS: SlashCommandsItem[] = [
    {
        title: 'H1',
        command: (chain) => chain.toggleHeading({ level: 1 }),
    },
    {
        title: 'H2',
        command: (chain) => chain.toggleHeading({ level: 2 }),
    },
    {
        title: 'H3',
        command: (chain) => chain.toggleHeading({ level: 3 }),
    },
    {
        title: 'B',
        command: (chain) => chain.toggleBold(),
    },
    {
        title: 'I',
        command: (chain) => chain.toggleItalic(),
    },
]

const SLASH_COMMANDS: SlashCommandsItem[] = [
    {
        title: 'HogQL',
        search: 'sql',
        icon: <IconQueryEditor />,
        command: (chain) =>
            chain.insertContent({ type: NotebookNodeType.Query, attrs: { query: examples['HogQLTable'] } }),
    },
    {
        title: 'Events',
        search: 'data explore',
        icon: <IconTableChart />,
        command: (chain) =>
            chain.insertContent({ type: NotebookNodeType.Query, attrs: { query: examples['EventsTableFull'] } }),
    },
    {
        title: 'Persons',
        search: 'people users',
        icon: <IconCohort />,
        command: (chain) =>
            chain.insertContent({ type: NotebookNodeType.Query, attrs: { query: examples['PersonsTableFull'] } }),
    },
    {
        title: 'Session Replays',
        search: 'recordings video',
        icon: <IconRecording />,
        command: (chain) => chain.insertContent({ type: NotebookNodeType.RecordingPlaylist, attrs: {} }),
    },
    {
        title: 'Funnel',
        search: 'Funnel',
        icon: <IconFunnelHorizontal />,
        command: (chain) => chain.insertContent({ type: NotebookNodeType.Query, attrs: { query: QUERY_FUNNEL } }),
    },
    {
        title: 'Trend',
        search: 'Trend',
        icon: <IconTrendUp />,
        command: (chain) => chain.insertContent({ type: NotebookNodeType.Query, attrs: { query: QUERY_TREND } }),
    },

    {
        title: 'Image',
        search: 'picture',
        icon: <IconUploadFile />,
        command: async (chain) => {
            // Trigger upload followed by insert
            try {
                const files = await selectFile({ contentType: 'image/*', multiple: false })

                if (files.length) {
                    return chain.insertContent({ type: NotebookNodeType.Image, attrs: { file: files[0] } })
                }
            } catch (e) {
                lemonToast.error('Something went wrong when trying to select a file.')
            }

            return chain
        },
    },
]

export const SlashCommands = forwardRef<SlashCommandsRef, SlashCommandsProps>(function SlashCommands(
    { mode, range = { from: 0, to: 0 }, query },
    ref
): JSX.Element | null {
    const { editor } = useValues(notebookLogic)
    // We start with 1 because the first item is the text controls
    const [selectedIndex, setSelectedIndex] = useState(0)
    const [selectedHorizontalIndex, setSelectedHorizontalIndex] = useState(0)

    const allCommmands = [...TEXT_CONTROLS, ...SLASH_COMMANDS]

    const fuse = useMemo(() => {
        return new Fuse(allCommmands, {
            keys: ['title', 'search'],
            threshold: 0.3,
        })
    }, [allCommmands])

    const filteredCommands = useMemo(() => {
        if (!query) {
            return allCommmands
        }
        return fuse.search(query).map((result) => result.item)
    }, [query, fuse])

    const filteredSlashCommands = useMemo(
        () => filteredCommands.filter((item) => SLASH_COMMANDS.includes(item)),
        [filteredCommands]
    )

    useEffect(() => {
        setSelectedIndex(0)
        setSelectedHorizontalIndex(0)
    }, [query])

    const onPressEnter = async (): Promise<void> => {
        if (!!editor) {
            const command =
                selectedIndex === -1
                    ? TEXT_CONTROLS[selectedHorizontalIndex].command
                    : filteredSlashCommands[selectedIndex].command

            const partialCommand = await command(editor.deleteRange(range))
            partialCommand.run()
        }
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

    const onKeyDown = useCallback(
        (event: KeyboardEvent): boolean => {
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
        [selectedIndex, selectedHorizontalIndex, filteredCommands]
    )

    // Expose the keydown handler to the tiptap extension
    useImperativeHandle(ref, () => ({ onKeyDown }), [onKeyDown])

    useEffect(() => {
        if (mode !== 'add') {
            return
        }

        // If not opened from a slash command, we want to add our own keyboard listeners
        const keyDownListener = (event: KeyboardEvent): void => {
            const preventDefault = onKeyDown(event)
            if (preventDefault) {
                event.preventDefault()
            }
        }

        window.addEventListener('keydown', keyDownListener, true)

        return () => window.removeEventListener('keydown', keyDownListener, true)
    }, [onKeyDown, mode])

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
                        onClick={async () => (await item.command(editor.deleteRange(range))).run()}
                    >
                        {item.title}
                    </LemonButton>
                ))}
            </div>

            <LemonDivider className="my-2" />

            {filteredSlashCommands.map((item, index) => (
                <LemonButton
                    key={item.title}
                    fullWidth
                    status="primary-alt"
                    icon={item.icon}
                    active={index === selectedIndex}
                    onClick={async () => (await item.command(editor.deleteRange(range))).run()}
                >
                    {item.title}
                </LemonButton>
            ))}

            {filteredSlashCommands.length === 0 && (
                <div className="text-muted-alt p-1">
                    Nothing matching <code>/{query}</code>
                </div>
            )}

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

export const SlashCommandsExtension = Extension.create({
    name: 'slash-commands',

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
