import { Extension } from '@tiptap/core'
import { ReactRenderer } from '@tiptap/react'
import Suggestion from '@tiptap/suggestion'
import { useValues } from 'kea'
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useState } from 'react'

import {
    IconCode,
    IconCursor,
    IconDatabase,
    IconFunnels,
    IconGraph,
    IconHogQL,
    IconLifecycle,
    IconPeople,
    IconPython,
    IconRetention,
    IconRewindPlay,
    IconSquareRoot,
    IconStickiness,
    IconTrends,
    IconUpload,
    IconUserPaths,
} from '@posthog/icons'
import { LemonButton, LemonDivider, lemonToast } from '@posthog/lemon-ui'

import { EditorCommands, EditorRange } from 'lib/components/RichContentEditor/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconBold, IconItalic, IconTableChart } from 'lib/lemon-ui/icons'
import { LemonMenu, LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { Popover } from 'lib/lemon-ui/Popover'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isKeyOf } from 'lib/utils'
import { selectFiles } from 'lib/utils/file-utils'
import { createFuse } from 'lib/utils/fuseSearch'
import { ValueOf } from 'lib/utils/types'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, FunnelVizType, PathType, RetentionPeriod } from '~/types'

import { addInsightsToNotebookModalLogic } from '../AddInsightsToNotebookModal/addInsightsToNotebookModalLogic'
import { buildNodeEmbed } from '../Nodes/NotebookNodeEmbed'
import { buildInsightVizQueryContent, buildNodeQueryContent } from '../Nodes/NotebookNodeQuery'
import { NotebookNodeType } from '../types'
import NotebookIconHeading from './NotebookIconHeading'
import { notebookLogic } from './notebookLogic'

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
    featureFlag?: ValueOf<typeof FEATURE_FLAGS>
}

type SlashCommandCategory = {
    title: string
    icon?: JSX.Element
    items: SlashCommandsItem[]
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

const SLASH_COMMAND_CATEGORIES: SlashCommandCategory[] = [
    {
        title: 'Insight',
        icon: <IconGraph color="currentColor" />,
        items: [
            {
                title: 'Trend',
                search: 'graph trend insight',
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
                                funnelVizType: FunnelVizType.Steps,
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
                                totalIntervals: 11,
                                targetEntity: {
                                    id: '$pageview',
                                    name: '$pageview',
                                    type: 'events',
                                },
                                returningEntity: {
                                    id: '$pageview',
                                    name: '$pageview',
                                    type: 'events',
                                },
                                retentionType: 'retention_first_time',
                            },
                        })
                    ),
            },
            {
                title: 'Paths',
                search: 'user paths insight',
                icon: <IconUserPaths color="currentColor" />,
                command: (chain, pos) =>
                    chain.insertContentAt(
                        pos,
                        buildInsightVizQueryContent({
                            kind: NodeKind.PathsQuery,
                            pathsFilter: {
                                includeEventTypes: [PathType.PageView],
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
                title: 'Saved insight',
                search: 'insight saved existing browse',
                icon: <IconGraph color="currentColor" />,
                command: (chain, pos) => {
                    addInsightsToNotebookModalLogic.actions.openModal(typeof pos === 'number' ? pos : null)
                    return chain
                },
            },
        ],
    },
    {
        title: 'SQL',
        icon: <IconHogQL color="currentColor" />,
        items: [
            {
                title: 'SQL',
                search: 'sql hogql query',
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
                title: 'SQL (DuckDB)',
                search: 'duck sql',
                icon: <IconHogQL color="currentColor" />,
                command: (chain, pos) =>
                    chain.insertContentAt(pos, {
                        type: NotebookNodeType.DuckSQL,
                        attrs: {
                            code: '',
                            returnVariable: 'duck_df',
                            __init: {
                                showSettings: true,
                            },
                        },
                    }),
                featureFlag: FEATURE_FLAGS.NOTEBOOK_PYTHON,
            },
            {
                title: 'SQL (HogQL)',
                search: 'hogql sql',
                icon: <IconHogQL color="currentColor" />,
                command: (chain, pos) =>
                    chain.insertContentAt(pos, {
                        type: NotebookNodeType.HogQLSQL,
                        attrs: {
                            code: '',
                            returnVariable: 'hogql_df',
                            __init: {
                                showSettings: true,
                            },
                        },
                    }),
                featureFlag: FEATURE_FLAGS.NOTEBOOK_PYTHON,
            },
            {
                title: 'Python',
                search: 'python',
                icon: <IconPython color="currentColor" />,
                command: (chain, pos) =>
                    chain.insertContentAt(pos, {
                        type: NotebookNodeType.Python,
                        attrs: {
                            code: '',
                            __init: {
                                showSettings: true,
                            },
                        },
                    }),
                featureFlag: FEATURE_FLAGS.NOTEBOOK_PYTHON,
            },
        ],
    },
    {
        title: 'Data',
        icon: <IconDatabase />,
        items: [
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
                title: 'People',
                search: 'persons users',
                icon: <IconPeople />,
                command: (chain, pos) =>
                    chain.insertContentAt(
                        pos,
                        buildNodeQueryContent({
                            kind: NodeKind.DataTableNode,
                            columns: defaultDataTableColumns(NodeKind.ActorsQuery),
                            source: {
                                kind: NodeKind.ActorsQuery,
                                select: defaultDataTableColumns(NodeKind.ActorsQuery),
                                properties: [],
                            },
                        })
                    ),
            },
            {
                title: 'Session recordings',
                search: 'video replay',
                icon: <IconRewindPlay />,
                command: (chain, pos) =>
                    chain.insertContentAt(pos, { type: NotebookNodeType.RecordingPlaylist, attrs: {} }),
            },
        ],
    },
    {
        title: 'Media',
        icon: <IconUpload />,
        items: [
            {
                title: 'Image',
                search: 'picture gif',
                icon: <IconUpload />,
                command: async (chain, pos) => {
                    // Trigger upload followed by insert
                    try {
                        const files = await selectFiles({ contentType: 'image/*', multiple: false })

                        if (files.length) {
                            return chain.insertContentAt(pos, {
                                type: NotebookNodeType.Image,
                                attrs: { file: files[0] },
                            })
                        }
                    } catch {
                        lemonToast.error('Something went wrong when trying to select a file.')
                    }

                    return chain
                },
            },
            {
                title: 'Table',
                search: 'table grid spreadsheet',
                icon: <IconTableChart />,
                command: (chain, pos) =>
                    chain.insertContentAt(pos, {
                        type: 'table',
                        content: [
                            {
                                type: 'tableRow',
                                content: [
                                    { type: 'tableCell', content: [{ type: 'paragraph' }] },
                                    { type: 'tableCell', content: [{ type: 'paragraph' }] },
                                    { type: 'tableCell', content: [{ type: 'paragraph' }] },
                                ],
                            },
                            {
                                type: 'tableRow',
                                content: [
                                    { type: 'tableCell', content: [{ type: 'paragraph' }] },
                                    { type: 'tableCell', content: [{ type: 'paragraph' }] },
                                    { type: 'tableCell', content: [{ type: 'paragraph' }] },
                                ],
                            },
                            {
                                type: 'tableRow',
                                content: [
                                    { type: 'tableCell', content: [{ type: 'paragraph' }] },
                                    { type: 'tableCell', content: [{ type: 'paragraph' }] },
                                    { type: 'tableCell', content: [{ type: 'paragraph' }] },
                                ],
                            },
                        ],
                    }),
            },
            {
                title: 'Embedded iframe',
                search: 'iframe embed',
                icon: <IconCode />,
                command: async (chain, pos) => {
                    return chain.insertContentAt(pos, buildNodeEmbed())
                },
            },
            {
                title: 'LaTeX',
                search: 'latex math formula equation',
                icon: <IconSquareRoot color="currentColor" />,
                command: (chain, pos) =>
                    chain.insertContentAt(pos, {
                        type: NotebookNodeType.Latex,
                        attrs: { content: '' }, // Default empty content
                    }),
            },
        ],
    },
]

/** Flatten all categories into a single list of commands, respecting feature flags. */
function flattenCommands(
    categories: SlashCommandCategory[],
    featureFlags: Record<string, boolean | string | undefined>
): SlashCommandsItem[] {
    return categories.flatMap((category) =>
        category.items.filter((item) => !item.featureFlag || featureFlags[item.featureFlag])
    )
}

export const SlashCommands = forwardRef<SlashCommandsRef, SlashCommandsProps>(function SlashCommands(
    { mode, range, getPos, onClose, query }: SlashCommandsProps,
    ref
): JSX.Element | null {
    const { editor } = useValues(notebookLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    // We start with 1 because the first item is the text controls
    const [selectedIndex, setSelectedIndex] = useState(0)
    const [selectedHorizontalIndex, setSelectedHorizontalIndex] = useState(0)

    const allFlatCommands = useMemo(() => flattenCommands(SLASH_COMMAND_CATEGORIES, featureFlags), [featureFlags])
    const allCommmands = [...TEXT_CONTROLS, ...allFlatCommands]

    const fuse = useMemo(() => {
        return createFuse(allCommmands, {
            keys: ['title', 'search'],
        })
        // oxlint-disable-next-line exhaustive-deps
    }, [allCommmands])

    const isSearching = !!query

    const filteredCommands = useMemo(() => {
        if (!query) {
            return allCommmands
        }
        return fuse.search(query).map((result) => result.item)
        // oxlint-disable-next-line exhaustive-deps
    }, [query, fuse])

    const filteredSlashCommands = useMemo(
        () => filteredCommands.filter((item) => allFlatCommands.includes(item)),
        [filteredCommands, allFlatCommands]
    )

    useEffect(() => {
        setSelectedIndex(0)
        setSelectedHorizontalIndex(0)
    }, [query])

    const execute = useCallback(
        async (item: SlashCommandsItem): Promise<void> => {
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
        },
        // oxlint-disable-next-line exhaustive-deps
        [editor, mode, range, getPos, onClose]
    )

    const onPressEnter = async (): Promise<void> => {
        const command =
            selectedIndex === -1 ? TEXT_CONTROLS[selectedHorizontalIndex] : filteredSlashCommands[selectedIndex]

        await execute(command)
    }
    const onPressUp = (): void => {
        setSelectedIndex(Math.max(selectedIndex - 1, -1))
    }
    const onPressDown = (): void => {
        setSelectedIndex(Math.min(selectedIndex + 1, allFlatCommands.length - 1))
    }

    const onPressLeft = (): void => {
        setSelectedHorizontalIndex(Math.max(selectedHorizontalIndex - 1, 0))
    }
    const onPressRight = (): void => {
        setSelectedHorizontalIndex(Math.min(selectedHorizontalIndex + 1, TEXT_CONTROLS.length - 1))
    }

    const onKeyDown = useCallback(
        (event: KeyboardEvent): boolean => {
            if (isSearching) {
                // When searching, keep the flat list keyboard navigation
                const keyMappings = {
                    ArrowUp: onPressUp,
                    ArrowDown: onPressDown,
                    ArrowLeft: onPressLeft,
                    ArrowRight: onPressRight,
                    Enter: onPressEnter,
                }

                if (isKeyOf(event.key, keyMappings)) {
                    keyMappings[event.key]()
                    return true
                }
            }

            return false
        },
        // oxlint-disable-next-line exhaustive-deps
        [selectedIndex, selectedHorizontalIndex, filteredCommands, isSearching]
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

    /** Build categorized menu data for the non-search view. */
    const categorizedMenuData = useMemo(
        () =>
            SLASH_COMMAND_CATEGORIES.flatMap((category) => {
                const availableItems = category.items.filter(
                    (item) => !item.featureFlag || featureFlags[item.featureFlag]
                )
                if (availableItems.length === 0) {
                    return []
                }
                return [
                    {
                        title: category.title,
                        icon: category.icon,
                        menuItems: availableItems.map(
                            (item): LemonMenuItem => ({
                                label: item.title,
                                icon: item.icon,
                                onClick: () => void execute(item),
                            })
                        ),
                    },
                ]
            }),
        [featureFlags, execute]
    )

    if (!editor) {
        return null
    }

    return (
        <div className="deprecated-space-y-px">
            <div className="flex items-center gap-1">
                {TEXT_CONTROLS.map((item, index) => (
                    <LemonButton
                        key={item.title}
                        size="small"
                        active={selectedIndex === -1 && selectedHorizontalIndex === index}
                        onClick={() => void execute(item)}
                        icon={item.icon}
                    />
                ))}
            </div>

            <LemonDivider />

            {isSearching ? (
                // When searching, show a flat filtered list so all items are discoverable
                <>
                    {filteredSlashCommands.map((item, index) => (
                        <LemonButton
                            key={item.title}
                            fullWidth
                            icon={item.icon}
                            active={index === selectedIndex}
                            onClick={() => void execute(item)}
                        >
                            {item.title}
                        </LemonButton>
                    ))}

                    {filteredSlashCommands.length === 0 && (
                        <div className="text-secondary p-1">
                            Nothing matching <code>/{query}</code>
                        </div>
                    )}
                </>
            ) : (
                // When not searching, show categorized nested menus
                <div className="deprecated-space-y-px">
                    {categorizedMenuData.map((category) => (
                        <LemonMenu
                            key={category.title}
                            items={category.menuItems}
                            placement="right-start"
                            trigger="hover"
                            closeParentPopoverOnClickInside
                        >
                            <LemonButton fullWidth icon={category.icon} size="small">
                                {category.title}
                            </LemonButton>
                        </LemonMenu>
                    ))}
                </div>
            )}

            {mode === 'add' && (
                <>
                    <LemonDivider className="my-0" />
                    <div className="text-xs text-secondary p-1">
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

    // Higher than NotebookDefaultBlockOnEnter (200) so slash popover handles Enter first
    priority: 300,

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
