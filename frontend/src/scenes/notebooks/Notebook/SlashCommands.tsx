import { Extension } from '@tiptap/core'
import Suggestion from '@tiptap/suggestion'

import { ReactRenderer } from '@tiptap/react'
import { LemonButton, LemonDivider, lemonToast } from '@posthog/lemon-ui'
import { IconBold, IconCohort, IconItalic } from 'lib/lemon-ui/icons'
import {
    IconCursor,
    IconFunnels,
    IconHogQL,
    IconLifecycle,
    IconRetention,
    IconRewindPlay,
    IconStickiness,
    IconTrends,
    IconUpload,
    IconUserPaths,
} from '@posthog/icons'
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useState } from 'react'
import { EditorCommands, EditorRange } from './utils'
import { BaseMathType, ChartDisplayType, FunnelVizType, NotebookNodeType, PathType, RetentionPeriod } from '~/types'
import { Popover } from 'lib/lemon-ui/Popover'
import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import Fuse from 'fuse.js'
import { useValues } from 'kea'
import { notebookLogic } from './notebookLogic'
import { selectFile } from '../Nodes/utils'
import NotebookIconHeading from './NotebookIconHeading'
import { NodeKind } from '~/queries/schema'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { buildInsightVizQueryContent, buildNodeQueryContent } from '../Nodes/NotebookNodeQuery'

type SlashCommandConditionalProps =
    | {
          mode: 'add'
          getPos: () => number
          range?: never
      }
    | {
          mode: 'slash'
          getPos?: never
          range: EditorRange
      }

type SlashCommandsProps = SlashCommandConditionalProps & {
    query?: string
    decorationNode?: any
    onClose?: () => void
}

type SlashCommandsPopoverProps = SlashCommandsProps & {
    visible: boolean
    children?: JSX.Element
}

type SlashCommandsRef = {
    onKeyDown: (event: KeyboardEvent) => boolean
}

type SlashCommandsItem = {
    title: string
    search?: string
    icon?: JSX.Element
    command: (chain: EditorCommands, pos: number | EditorRange) => EditorCommands | Promise<EditorCommands>
}

const TEXT_CONTROLS: SlashCommandsItem[] = [
    {
        title: 'h1',
        icon: <NotebookIconHeading level={1} />,
        command: (chain) => chain.toggleHeading({ level: 1 }),
    },
    {
        title: 'h2',
        icon: <NotebookIconHeading level={2} />,
        command: (chain) => chain.toggleHeading({ level: 2 }),
    },
    {
        title: 'h3',
        icon: <NotebookIconHeading level={3} />,
        command: (chain) => chain.toggleHeading({ level: 3 }),
    },
    {
        title: 'bold',
        icon: <IconBold />,
        command: (chain) => chain.toggleBold(),
    },
    {
        title: 'italic',
        icon: <IconItalic />,
        command: (chain) => chain.toggleItalic(),
    },
]

const SLASH_COMMANDS: SlashCommandsItem[] = [
    {
        title: 'Trend',
        search: 'trend insight',
        icon: <IconTrends color="currentColor" />,
        command: (chain, pos) =>
            chain.insertContentAt(
                pos,
                buildInsightVizQueryContent({
                    kind: NodeKind.TrendsQuery,
                    filterTestAccounts: false,
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            event: '$pageview',
                            name: '$pageview',
                            math: BaseMathType.TotalCount,
                        },
                    ],
                    interval: 'day',
                    trendsFilter: {
                        display: ChartDisplayType.ActionsLineGraph,
                    },
                })
            ),
    },
    {
        title: 'Funnel',
        search: 'funnel insight',
        icon: <IconFunnels color="currentColor" />,
        command: (chain, pos) =>
            chain.insertContentAt(
                pos,
                buildInsightVizQueryContent({
                    kind: NodeKind.FunnelsQuery,
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                        },
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                        },
                    ],
                    funnelsFilter: {
                        funnel_viz_type: FunnelVizType.Steps,
                    },
                })
            ),
    },
    {
        title: 'Retention',
        search: 'retention insight',
        icon: <IconRetention color="currentColor" />,
        command: (chain, pos) =>
            chain.insertContentAt(
                pos,
                buildInsightVizQueryContent({
                    kind: NodeKind.RetentionQuery,
                    retentionFilter: {
                        period: RetentionPeriod.Day,
                        total_intervals: 11,
                        target_entity: {
                            id: '$pageview',
                            name: '$pageview',
                            type: 'events',
                        },
                        returning_entity: {
                            id: '$pageview',
                            name: '$pageview',
                            type: 'events',
                        },
                        retention_type: 'retention_first_time',
                    },
                })
            ),
    },
    {
        title: 'Paths',
        search: 'paths insight',
        icon: <IconUserPaths color="currentColor" />,
        command: (chain, pos) =>
            chain.insertContentAt(
                pos,
                buildInsightVizQueryContent({
                    kind: NodeKind.PathsQuery,
                    pathsFilter: {
                        include_event_types: [PathType.PageView],
                    },
                })
            ),
    },
    {
        title: 'Stickiness',
        search: 'stickiness insight',
        icon: <IconStickiness color="currentColor" />,
        command: (chain, pos) =>
            chain.insertContentAt(
                pos,
                buildInsightVizQueryContent({
                    kind: NodeKind.StickinessQuery,
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                            math: BaseMathType.TotalCount,
                        },
                    ],
                    stickinessFilter: {},
                })
            ),
    },
    {
        title: 'Lifecycle',
        search: 'lifecycle insight',
        icon: <IconLifecycle color="currentColor" />,
        command: (chain, pos) =>
            chain.insertContentAt(
                pos,
                buildInsightVizQueryContent({
                    kind: NodeKind.LifecycleQuery,
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                            math: BaseMathType.TotalCount,
                        },
                    ],
                })
            ),
    },
    {
        title: 'HogQL',
        search: 'sql',
        icon: <IconHogQL color="currentColor" />,
        command: (chain, pos) =>
            chain.insertContentAt(
                pos,
                buildNodeQueryContent({
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.HogQLQuery,
                        query: `select event,
        person.properties.email,
        properties.$browser,
        count()
    from events
    where {filters} -- replaced with global date and property filters
    and person.properties.email is not null
group by event,
        properties.$browser,
        person.properties.email
order by count() desc
    limit 100`,
                        filters: {
                            dateRange: {
                                date_from: '-24h',
                            },
                        },
                    },
                })
            ),
    },
    {
        title: 'Events',
        search: 'data explore',
        icon: <IconCursor />,
        command: (chain, pos) =>
            chain.insertContentAt(
                pos,
                buildNodeQueryContent({
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.EventsQuery,
                        select: defaultDataTableColumns(NodeKind.EventsQuery),
                        properties: [],
                        after: '-24h',
                        limit: 100,
                    },
                })
            ),
    },
    {
        title: 'Persons',
        search: 'people users',
        icon: <IconCohort />,
        command: (chain, pos) =>
            chain.insertContentAt(
                pos,
                buildNodeQueryContent({
                    kind: NodeKind.DataTableNode,
                    columns: defaultDataTableColumns(NodeKind.PersonsNode),
                    source: {
                        kind: NodeKind.PersonsNode,
                        properties: [],
                    },
                })
            ),
    },
    {
        title: 'Session Replays',
        search: 'recordings video',
        icon: <IconRewindPlay />,
        command: (chain, pos) => chain.insertContentAt(pos, { type: NotebookNodeType.RecordingPlaylist, attrs: {} }),
    },
    {
        title: 'Image',
        search: 'picture',
        icon: <IconUpload />,
        command: async (chain, pos) => {
            // Trigger upload followed by insert
            try {
                const files = await selectFile({ contentType: 'image/*', multiple: false })

                if (files.length) {
                    return chain.insertContentAt(pos, { type: NotebookNodeType.Image, attrs: { file: files[0] } })
                }
            } catch (e) {
                lemonToast.error('Something went wrong when trying to select a file.')
            }

            return chain
        },
    },
]

export const SlashCommands = forwardRef<SlashCommandsRef, SlashCommandsProps>(function SlashCommands(
    { mode, range, getPos, onClose, query }: SlashCommandsProps,
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

    const execute = async (item: SlashCommandsItem): Promise<void> => {
        if (editor) {
            const selectedNode = editor.getSelectedNode()
            const isTextNode = selectedNode === null || selectedNode.isText
            const isTextCommand = TEXT_CONTROLS.map((c) => c.title).includes(item.title)

            const position = mode === 'slash' ? range.from : getPos()
            let chain = mode === 'slash' ? editor.deleteRange(range) : editor.chain()

            if (!isTextNode && isTextCommand) {
                chain = chain.insertContentAt(position, { type: 'paragraph' })
            }

            const partialCommand = await item.command(chain, position)
            partialCommand.run()

            onClose?.()
        }
    }

    const onPressEnter = async (): Promise<void> => {
        const command =
            selectedIndex === -1 ? TEXT_CONTROLS[selectedHorizontalIndex] : filteredSlashCommands[selectedIndex]

        await execute(command)
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
        <div className="space-y-px">
            <div className="flex items-center gap-1">
                {TEXT_CONTROLS.map((item, index) => (
                    <LemonButton
                        key={item.title}
                        status="primary-alt"
                        size="small"
                        active={selectedIndex === -1 && selectedHorizontalIndex === index}
                        onClick={async () => await execute(item)}
                        icon={item.icon}
                    />
                ))}
            </div>

            <LemonDivider />

            {filteredSlashCommands.map((item, index) => (
                <LemonButton
                    key={item.title}
                    fullWidth
                    status="primary-alt"
                    icon={item.icon}
                    active={index === selectedIndex}
                    onClick={async () => await execute(item)}
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

export const SlashCommandsPopover = forwardRef<SlashCommandsRef, SlashCommandsPopoverProps>(
    function SlashCommandsPopover(
        { visible = true, decorationNode, children, onClose, ...props }: SlashCommandsPopoverProps,
        ref
    ): JSX.Element | null {
        return (
            <Popover
                placement="right-start"
                fallbackPlacements={['left-start', 'right-end']}
                overlay={<SlashCommands ref={ref} onClose={onClose} {...props} />}
                referenceElement={decorationNode}
                visible={visible}
                onClickOutside={onClose}
            >
                {children}
            </Popover>
        )
    }
)

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
                                props: { ...props, mode: 'slash' },
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
