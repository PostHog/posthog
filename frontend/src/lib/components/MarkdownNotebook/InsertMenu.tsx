import clsx from 'clsx'
import { ReactNode, type CSSProperties, useEffect, useRef } from 'react'

import { IconCode, IconDatabase, IconGraph, IconList, IconPencil, IconSparkles } from '@posthog/icons'

import { Scene } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

import {
    INSERT_MENU_GAP,
    INSERT_MENU_MAX_HEIGHT,
    INSERT_MENU_MIN_HEIGHT,
    INSERT_MENU_VIEWPORT_PADDING,
    INSERT_MENU_WIDTH,
    InsertCommand,
    InsertMenuPosition,
    InsertMenuSelectionDirection,
} from './editorTypes'
import { makeEmptyParagraph } from './markdown'
import { getMarkdownNotebookComponentDefaultProps } from './registry'
import {
    NotebookBlockNode,
    NotebookComponentBlockNode,
    NotebookComponentDefinition,
    NotebookComponentProps,
    NotebookComponentRegistry,
} from './types'

/** DOM id of a command's option element, referenced by the editor's `aria-activedescendant`. */
export function getInsertMenuOptionDomId(menuId: string, commandKey: string): string {
    return `${menuId}-option-${commandKey}`
}

export function InsertMenu({
    id,
    query,
    commands,
    targetNodeId,
    position,
    selectedIndex,
    onClose,
}: {
    id?: string
    query: string
    commands: InsertCommand[]
    targetNodeId: string
    position: InsertMenuPosition | null
    selectedIndex: number
    onClose: () => void
}): JSX.Element {
    const selectedItemRef = useRef<HTMLButtonElement | null>(null)
    const filteredCommands = getFilteredInsertCommands(commands, query)
    const commandsByCategory = groupInsertCommandsByCategory(filteredCommands)
    const selectedCommandIndex = getClampedInsertMenuSelectedIndex(selectedIndex, filteredCommands.length)
    const selectedCommand = filteredCommands[selectedCommandIndex]
    const selectedCommandKey = selectedCommand?.key
    const menuStyle = position
        ? ({
              '--markdown-notebook-insert-menu-left': `${position.left}px`,
              '--markdown-notebook-insert-menu-max-height': `${position.maxHeight}px`,
              '--markdown-notebook-insert-menu-top': `${position.top}px`,
              '--markdown-notebook-insert-menu-width': `${position.width}px`,
          } as CSSProperties)
        : undefined

    useEffect(() => {
        selectedItemRef.current?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
    }, [selectedCommandKey])

    return (
        <div
            className={clsx(
                'MarkdownNotebook__insert-menu',
                position && 'MarkdownNotebook__insert-menu--positioned',
                position && `MarkdownNotebook__insert-menu--${position.placement}`
            )}
            contentEditable={false}
            style={menuStyle}
            id={id}
            role="listbox"
            aria-label="Insert block"
        >
            {/* Focus stays in the editor while the menu is open, so screen readers may miss the
                aria-activedescendant change — announce the selection explicitly. */}
            <div className="sr-only" aria-live="polite">
                {selectedCommand
                    ? `${selectedCommand.label}, ${selectedCommandIndex + 1} of ${filteredCommands.length}`
                    : 'No components found'}
            </div>
            {Object.entries(commandsByCategory).map(([category, categoryCommands]) => (
                <div className="MarkdownNotebook__insert-category" key={category} role="group" aria-label={category}>
                    <h5 aria-hidden="true">{category}</h5>
                    <div className="MarkdownNotebook__insert-grid">
                        {categoryCommands.map((command) => (
                            <button
                                ref={command.key === selectedCommandKey ? selectedItemRef : null}
                                className={clsx(
                                    'MarkdownNotebook__insert-item',
                                    command.key === selectedCommandKey && 'MarkdownNotebook__insert-item--selected'
                                )}
                                key={command.key}
                                id={id ? getInsertMenuOptionDomId(id, command.key) : undefined}
                                role="option"
                                aria-selected={command.key === selectedCommandKey}
                                disabled={command.disabled}
                                type="button"
                                onClick={() => {
                                    if (command.disabled) {
                                        return
                                    }
                                    command.run(targetNodeId)
                                    if (command.closeOnRun !== false) {
                                        onClose()
                                    }
                                }}
                            >
                                {command.icon ? (
                                    <span className="MarkdownNotebook__insert-item-icon">{command.icon}</span>
                                ) : null}
                                <span>{renderHighlightedInsertCommandLabel(command.label, query)}</span>
                            </button>
                        ))}
                    </div>
                </div>
            ))}
            {!filteredCommands.length ? <div className="MarkdownNotebook__empty-menu">No components found</div> : null}
        </div>
    )
}

export function renderHighlightedInsertCommandLabel(label: string, query: string): ReactNode {
    const normalizedQuery = query.trim().toLowerCase()
    const matchIndex = normalizedQuery ? label.toLowerCase().indexOf(normalizedQuery) : -1
    if (matchIndex === -1) {
        return label
    }

    const matchEndIndex = matchIndex + normalizedQuery.length
    return (
        <>
            {label.slice(0, matchIndex)}
            <mark className="MarkdownNotebook__insert-item-highlight">{label.slice(matchIndex, matchEndIndex)}</mark>
            {label.slice(matchEndIndex)}
        </>
    )
}

export function getFilteredInsertCommands(commands: InsertCommand[], query: string): InsertCommand[] {
    const normalizedQuery = query.trim().toLowerCase()
    if (!normalizedQuery) {
        return commands
    }

    return commands.filter((command) => getInsertCommandSearchText(command).includes(normalizedQuery))
}

export function getInsertCommandSearchText(command: InsertCommand): string {
    return `${command.label} ${command.category} ${command.description ?? ''} ${(command.aliases ?? []).join(' ')}`
        .trim()
        .toLowerCase()
}

export function groupInsertCommandsByCategory(commands: InsertCommand[]): Record<string, InsertCommand[]> {
    return commands.reduce<Record<string, InsertCommand[]>>((accumulator, command) => {
        accumulator[command.category] = [...(accumulator[command.category] ?? []), command]
        return accumulator
    }, {})
}

export function getClampedInsertMenuSelectedIndex(selectedIndex: number, commandCount: number): number {
    if (commandCount <= 0) {
        return 0
    }
    return Math.max(0, Math.min(selectedIndex, commandCount - 1))
}

export function getNextInsertMenuSelectedIndex(
    selectedIndex: number,
    commandCount: number,
    direction: InsertMenuSelectionDirection
): number {
    if (commandCount <= 0) {
        return 0
    }

    const clampedIndex = getClampedInsertMenuSelectedIndex(selectedIndex, commandCount)
    return direction === 'next' ? (clampedIndex + 1) % commandCount : (clampedIndex - 1 + commandCount) % commandCount
}

export function buildInsertCommands(
    registry: NotebookComponentRegistry,
    replaceNodeWithInsertedComponent: (nodeId: string, nextNode: NotebookComponentBlockNode) => void,
    replaceNode: (nodeId: string, nextNode: NotebookBlockNode) => void,
    focusInsertedText: (nodeId: string) => void,
    focusInsertedTable: (nodeId: string) => void,
    focusInsertedCode: (nodeId: string) => void,
    openAIPrompt?: (nodeId: string) => void,
    isAskAIDisabled?: boolean,
    extraCommands: InsertCommand[] = []
): InsertCommand[] {
    const commonCategory = 'Common'

    const insertComponent = (targetNodeId: string, tagName: string, props: NotebookComponentProps): void => {
        const node: NotebookComponentBlockNode = {
            id: makeEmptyParagraph(`component-${tagName}`).id,
            type: 'component',
            tagName,
            props,
        }

        replaceNodeWithInsertedComponent(targetNodeId, node)
    }

    const insertRegisteredComponent = (targetNodeId: string, tagName: string, props?: NotebookComponentProps): void => {
        const definition = registry.components[tagName]
        if (!definition) {
            return
        }

        insertComponent(targetNodeId, tagName, props ?? getMarkdownNotebookComponentDefaultProps(definition))
    }

    const getRegisteredComponentInsertProps = (definition: NotebookComponentDefinition): NotebookComponentProps => {
        const insertDefaultProps = definition.insertCommand?.defaultProps
        if (typeof insertDefaultProps === 'function') {
            return insertDefaultProps()
        }
        return insertDefaultProps ?? getMarkdownNotebookComponentDefaultProps(definition)
    }

    const insertTable = (targetNodeId: string): void => {
        const nodeId = makeEmptyParagraph('table').id
        replaceNode(targetNodeId, {
            id: nodeId,
            type: 'table',
            headers: [
                { children: [{ type: 'text', text: 'Column 1' }] },
                { children: [{ type: 'text', text: 'Column 2' }] },
            ],
            rows: [[{ children: [] }, { children: [] }]],
        })
        focusInsertedTable(nodeId)
    }

    const insertCode = (targetNodeId: string): void => {
        replaceNode(targetNodeId, {
            id: targetNodeId,
            type: 'code',
            text: '',
        })
        focusInsertedCode(targetNodeId)
    }

    const aiCommands: InsertCommand[] = openAIPrompt
        ? [
              {
                  key: 'ai-ask',
                  label: 'Ask AI',
                  category: commonCategory,
                  description: 'Ask AI to write or edit this notebook',
                  aliases: ['ai', 'ask', 'posthog ai'],
                  icon: <IconSparkles />,
                  closeOnRun: false,
                  disabled: isAskAIDisabled,
                  run: openAIPrompt,
              },
          ]
        : []

    const queryCommands: InsertCommand[] = [
        {
            key: 'query-trend',
            label: 'Trend',
            category: 'Insight',
            icon: <IconGraph />,
            run: (targetNodeId) =>
                insertComponent(targetNodeId, 'Query', {
                    query: {
                        kind: 'InsightVizNode',
                        source: { kind: 'TrendsQuery', series: [{ event: '$pageview', kind: 'EventsNode' }] },
                    },
                }),
        },
        {
            key: 'query-funnel',
            label: 'Funnel',
            category: 'Insight',
            icon: <IconGraph />,
            run: (targetNodeId) =>
                insertComponent(targetNodeId, 'Query', {
                    query: {
                        kind: 'InsightVizNode',
                        source: {
                            kind: 'FunnelsQuery',
                            series: [
                                { event: '$pageview', kind: 'EventsNode' },
                                { event: '$pageleave', kind: 'EventsNode' },
                            ],
                        },
                    },
                }),
        },
    ]

    const sqlCommands: InsertCommand[] = [
        {
            key: 'query-sql',
            label: 'SQL',
            category: commonCategory,
            icon: <IconDatabase />,
            run: (targetNodeId) =>
                insertComponent(targetNodeId, 'Query', {
                    query: {
                        kind: 'DataTableNode',
                        source: { kind: 'HogQLQuery', query: 'select event, count() from events group by event' },
                    },
                }),
        },
    ]

    const dataCommands: InsertCommand[] = [
        {
            key: 'query-events',
            label: 'Events',
            category: 'Data',
            icon: <IconList />,
            run: (targetNodeId) =>
                insertComponent(targetNodeId, 'Query', {
                    query: {
                        kind: 'DataTableNode',
                        source: { kind: 'EventsQuery', select: ['*', 'event', 'person', 'timestamp'] },
                    },
                }),
        },
        {
            key: 'data-people',
            label: 'People',
            category: 'Data',
            icon: <IconList />,
            run: (targetNodeId) =>
                insertComponent(targetNodeId, 'Query', {
                    query: {
                        kind: 'DataTableNode',
                        source: {
                            kind: 'ActorsQuery',
                            select: ['person_display_name -- Person', 'id', 'created_at'],
                            // ActorsQuery hits ClickHouse, which requires a product query tag.
                            // Match the notebook query tagging convention (see NotebookSQLEditor).
                            tags: { productKey: ProductKey.NOTEBOOKS, scene: Scene.Notebook },
                        },
                    },
                }),
        },
        {
            key: 'data-session-recordings',
            label: 'Session recordings',
            category: 'Data',
            icon: <IconList />,
            run: (targetNodeId) => insertRegisteredComponent(targetNodeId, 'RecordingPlaylist'),
        },
    ]

    const mediaCommands: InsertCommand[] = [
        {
            key: 'media-image',
            label: 'Image',
            category: 'Media',
            icon: <IconList />,
            run: (targetNodeId) => insertRegisteredComponent(targetNodeId, 'Image'),
        },
        {
            key: 'media-table',
            label: 'Table',
            category: 'Media',
            icon: <IconList />,
            run: insertTable,
        },
        {
            key: 'media-iframe',
            label: 'Iframe',
            category: 'Media',
            icon: <IconList />,
            run: (targetNodeId) => insertRegisteredComponent(targetNodeId, 'Embed'),
        },
        {
            key: 'media-latex',
            label: 'LaTeX',
            category: 'Media',
            icon: <IconList />,
            run: (targetNodeId) => insertRegisteredComponent(targetNodeId, 'Latex'),
        },
    ]

    const componentCommands: InsertCommand[] = Object.values(registry.components).flatMap((definition) => {
        const insertCommand = definition.insertCommand
        if (!insertCommand) {
            return []
        }

        return [
            {
                key: `component-${definition.tagName}`,
                label: insertCommand.label ?? definition.label,
                category: insertCommand.category ?? definition.category,
                description: insertCommand.description ?? definition.description,
                aliases: insertCommand.aliases ?? definition.aliases,
                icon: insertCommand.icon ?? definition.icon,
                run: (targetNodeId) =>
                    insertRegisteredComponent(
                        targetNodeId,
                        definition.tagName,
                        getRegisteredComponentInsertProps(definition)
                    ),
            },
        ]
    })

    const textCommands: InsertCommand[] = [
        {
            key: 'text-paragraph',
            label: 'Text',
            category: commonCategory,
            aliases: ['paragraph', 'plain text'],
            icon: <IconPencil />,
            run: (targetNodeId) => {
                replaceNode(targetNodeId, {
                    id: targetNodeId,
                    type: 'paragraph',
                    children: [],
                })
                focusInsertedText(targetNodeId)
            },
        },
    ]

    const textStyleCommands: InsertCommand[] = [
        {
            key: 'text-quote',
            label: 'Blockquote',
            category: 'Text',
            aliases: ['quote'],
            icon: <IconPencil />,
            run: (targetNodeId) =>
                replaceNode(targetNodeId, {
                    id: targetNodeId,
                    type: 'blockquote',
                    children: [],
                }),
        },
        {
            key: 'text-code',
            label: 'Code',
            category: 'Text',
            aliases: ['code block', 'fenced code'],
            icon: <IconCode />,
            run: insertCode,
        },
        {
            key: 'text-heading-1',
            label: 'Heading 1',
            category: 'Text',
            aliases: ['h1'],
            icon: <IconPencil />,
            run: (targetNodeId) =>
                replaceNode(targetNodeId, {
                    id: targetNodeId,
                    type: 'heading',
                    level: 1,
                    children: [],
                }),
        },
        {
            key: 'text-heading-2',
            label: 'Heading 2',
            category: 'Text',
            aliases: ['h2'],
            icon: <IconPencil />,
            run: (targetNodeId) =>
                replaceNode(targetNodeId, {
                    id: targetNodeId,
                    type: 'heading',
                    level: 2,
                    children: [],
                }),
        },
        {
            key: 'text-heading-3',
            label: 'Heading 3',
            category: 'Text',
            aliases: ['h3'],
            icon: <IconPencil />,
            run: (targetNodeId) =>
                replaceNode(targetNodeId, {
                    id: targetNodeId,
                    type: 'heading',
                    level: 3,
                    children: [],
                }),
        },
    ]

    return [
        ...aiCommands,
        ...textCommands,
        ...sqlCommands,
        ...queryCommands,
        ...dataCommands,
        ...mediaCommands,
        ...componentCommands,
        ...textStyleCommands,
        ...extraCommands,
    ]
}

export function getInsertMenuPosition(anchorElement: HTMLElement): InsertMenuPosition {
    const anchorRect = anchorElement.getBoundingClientRect()
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight
    const availableViewportWidth = Math.max(0, viewportWidth - INSERT_MENU_VIEWPORT_PADDING * 2)
    const width = Math.min(INSERT_MENU_WIDTH, availableViewportWidth)
    const maxLeft = viewportWidth - INSERT_MENU_VIEWPORT_PADDING - width
    const left = Math.min(
        Math.max(INSERT_MENU_VIEWPORT_PADDING, anchorRect.left),
        Math.max(INSERT_MENU_VIEWPORT_PADDING, maxLeft)
    )
    const availableBelow = Math.max(
        0,
        viewportHeight - anchorRect.bottom - INSERT_MENU_GAP - INSERT_MENU_VIEWPORT_PADDING
    )
    const availableAbove = Math.max(0, anchorRect.top - INSERT_MENU_GAP - INSERT_MENU_VIEWPORT_PADDING)
    const placement = availableBelow >= INSERT_MENU_MIN_HEIGHT || availableBelow >= availableAbove ? 'below' : 'above'
    const availableHeight = placement === 'below' ? availableBelow : availableAbove

    return {
        placement,
        top: placement === 'below' ? anchorRect.bottom + INSERT_MENU_GAP : anchorRect.top - INSERT_MENU_GAP,
        left,
        width,
        maxHeight: Math.min(INSERT_MENU_MAX_HEIGHT, availableHeight),
    }
}
