import type { Meta, StoryObj } from '@storybook/react'
import {
    ColumnsIcon,
    CopyIcon,
    DatabaseIcon,
    FileIcon,
    FolderIcon,
    MoreHorizontalIcon,
    PencilIcon,
    TableIcon,
    TrashIcon,
} from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import { ContextMenuItem, ContextMenuSeparator } from './context-menu'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from './dropdown-menu'
import { Input } from './input'
import { Text } from './text'
import {
    Tree,
    TreeItemActions,
    TreeItemIcon,
    TreeItemLabel,
    TreeItemMeta,
    type TreeItemState,
    type TreeNode,
    type TreeProps,
} from './tree'

const meta: Meta<typeof Tree> = {
    title: 'Primitives/Tree',
    component: Tree,
    tags: ['autodocs'],
}

export default meta
type Story = StoryObj<typeof meta>

interface FileNode extends TreeNode {
    children?: FileNode[]
}

const FILES: FileNode[] = [
    {
        id: 'src',
        textValue: 'src',
        children: [
            {
                id: 'src/components',
                textValue: 'components',
                children: [
                    { id: 'src/components/button.tsx', textValue: 'button.tsx' },
                    { id: 'src/components/tree.tsx', textValue: 'tree.tsx' },
                ],
            },
            { id: 'src/index.ts', textValue: 'index.ts' },
            { id: 'src/legacy.ts', textValue: 'legacy.ts', disabledReason: 'Archived files are read-only' },
        ],
    },
    { id: 'package.json', textValue: 'package.json' },
    { id: 'README.md', textValue: 'README.md' },
]

function renderFile(node: FileNode, state: TreeItemState): React.ReactNode {
    return (
        <>
            <TreeItemIcon>{state.hasChildren ? <FolderIcon /> : <FileIcon />}</TreeItemIcon>
            <TreeItemLabel>{node.textValue}</TreeItemLabel>
        </>
    )
}

type ControlledProps<T extends TreeNode> = Omit<TreeProps<T>, 'expandedIds' | 'onExpandedIdsChange' | 'aria-label'> & {
    defaultExpandedIds?: string[]
    'aria-label'?: string
}

function ControlledTree<T extends TreeNode>({
    defaultExpandedIds = [],
    className,
    ...props
}: ControlledProps<T>): React.ReactElement {
    const [expandedIds, setExpandedIds] = React.useState(defaultExpandedIds)
    const [selectedId, setSelectedId] = React.useState<string | null>(null)
    return (
        <Tree<T>
            aria-label="Files"
            className={className ?? 'h-80 w-72 rounded-md border p-1'}
            expandedIds={expandedIds}
            onExpandedIdsChange={setExpandedIds}
            selectedId={selectedId}
            onSelectedIdChange={setSelectedId}
            {...props}
        />
    )
}

export const Basic: Story = {
    render: () => <ControlledTree items={FILES} defaultExpandedIds={['src']} renderItem={renderFile} />,
}

export const LazyChildren: Story = {
    render: function LazyChildrenStory() {
        const [items, setItems] = React.useState<FileNode[]>([
            { id: 'bucket-a', textValue: 'bucket-a', hasChildren: true },
            { id: 'bucket-b', textValue: 'bucket-b', hasChildren: true },
        ])
        const load = (node: FileNode): void => {
            setTimeout(() => {
                setItems((current) =>
                    current.map((item) =>
                        item.id === node.id
                            ? {
                                  ...item,
                                  children: Array.from({ length: 3 }, (_, index) => ({
                                      id: `${node.id}/object-${index}`,
                                      textValue: `object-${index}.parquet`,
                                  })),
                              }
                            : item
                    )
                )
            }, 800)
        }
        return (
            <ControlledTree
                items={items}
                onLoadChildren={load}
                renderItem={(node, state) => (
                    <>
                        <TreeItemIcon>{state.hasChildren ? <FolderIcon /> : <FileIcon />}</TreeItemIcon>
                        <TreeItemLabel>{node.textValue}</TreeItemLabel>
                        {state.expanded && node.hasChildren && !node.children && <TreeItemMeta>Loading…</TreeItemMeta>}
                    </>
                )}
            />
        )
    },
}

interface SchemaNode extends TreeNode {
    kind: 'section' | 'table' | 'column'
    meta?: string
    children?: SchemaNode[]
}

const SCHEMA: SchemaNode[] = [
    {
        id: 'posthog',
        textValue: 'PostHog',
        kind: 'section',
        section: true,
        children: [
            {
                id: 'events',
                textValue: 'events',
                kind: 'table',
                meta: '1.2M',
                children: [
                    { id: 'events.uuid', textValue: 'uuid', kind: 'column', meta: 'UUID' },
                    { id: 'events.event', textValue: 'event', kind: 'column', meta: 'String' },
                    { id: 'events.timestamp', textValue: 'timestamp', kind: 'column', meta: 'DateTime' },
                ],
            },
            {
                id: 'persons',
                textValue: 'persons',
                kind: 'table',
                meta: '48K',
                children: [
                    { id: 'persons.id', textValue: 'id', kind: 'column', meta: 'UUID' },
                    { id: 'persons.properties', textValue: 'properties', kind: 'column', meta: 'JSON' },
                ],
            },
        ],
    },
    {
        id: 'warehouse',
        textValue: 'Data warehouse',
        kind: 'section',
        section: true,
        children: [{ id: 'stripe_charges', textValue: 'stripe_charges', kind: 'table', meta: '9K' }],
    },
]

function schemaIcon(kind: SchemaNode['kind']): React.ReactNode {
    return kind === 'table' ? <TableIcon /> : kind === 'column' ? <ColumnsIcon /> : <DatabaseIcon />
}

export const SectionsActionsContextMenu: Story = {
    name: 'Sections + row actions + context menu',
    render: () => (
        <ControlledTree
            aria-label="Schema"
            items={SCHEMA}
            defaultExpandedIds={['posthog', 'warehouse', 'events']}
            renderItem={(node) => (
                <>
                    {!node.section && <TreeItemIcon>{schemaIcon(node.kind)}</TreeItemIcon>}
                    <TreeItemLabel>{node.textValue}</TreeItemLabel>
                    {node.meta && <TreeItemMeta>{node.meta}</TreeItemMeta>}
                    {node.kind === 'table' && (
                        <TreeItemActions>
                            <DropdownMenu>
                                <DropdownMenuTrigger
                                    render={<Button size="icon-xs" aria-label={`More actions for ${node.textValue}`} />}
                                >
                                    <MoreHorizontalIcon />
                                </DropdownMenuTrigger>
                                <DropdownMenuContent>
                                    <DropdownMenuItem>
                                        <CopyIcon />
                                        Copy name
                                    </DropdownMenuItem>
                                    <DropdownMenuItem>
                                        <PencilIcon />
                                        Rename…
                                    </DropdownMenuItem>
                                </DropdownMenuContent>
                            </DropdownMenu>
                        </TreeItemActions>
                    )}
                </>
            )}
            renderContextMenu={(node) =>
                node.kind === 'table' ? (
                    <>
                        <ContextMenuItem>
                            <CopyIcon />
                            Copy name
                        </ContextMenuItem>
                        <ContextMenuItem>
                            <PencilIcon />
                            Rename…
                        </ContextMenuItem>
                        <ContextMenuSeparator />
                        <ContextMenuItem variant="destructive">
                            <TrashIcon />
                            Delete
                        </ContextMenuItem>
                    </>
                ) : null
            }
        />
    ),
}

function filterTree<T extends TreeNode & { children?: T[] }>(nodes: T[], query: string): T[] {
    const needle = query.toLowerCase()
    return nodes.flatMap((node) => {
        const children = node.children ? filterTree(node.children, query) : undefined
        if (node.textValue.toLowerCase().includes(needle) || (children && children.length > 0)) {
            return [{ ...node, children }]
        }
        return []
    })
}

function collectBranchIds(nodes: TreeNode[]): string[] {
    return nodes.flatMap((node) => (node.children ? [node.id, ...collectBranchIds(node.children)] : []))
}

export const SearchHighlight: Story = {
    render: function SearchHighlightStory() {
        const [query, setQuery] = React.useState('tim')
        const [expandedIds, setExpandedIds] = React.useState<string[]>([])
        const items = React.useMemo(() => (query ? filterTree(SCHEMA, query) : SCHEMA), [query])
        // While searching, every branch that holds a match is open.
        const shownExpandedIds = query ? collectBranchIds(items) : expandedIds
        return (
            <div className="flex w-72 flex-col gap-2">
                <Input aria-label="Search schema" value={query} onChange={(event) => setQuery(event.target.value)} />
                <Tree
                    aria-label="Schema"
                    className="h-80 rounded-md border p-1"
                    items={items}
                    expandedIds={shownExpandedIds}
                    onExpandedIdsChange={setExpandedIds}
                    renderItem={(node) => (
                        <>
                            {!node.section && <TreeItemIcon>{schemaIcon(node.kind)}</TreeItemIcon>}
                            <TreeItemLabel highlight={query}>{node.textValue}</TreeItemLabel>
                            {node.meta && <TreeItemMeta>{node.meta}</TreeItemMeta>}
                        </>
                    )}
                    empty={
                        <Text size="xs" variant="muted" className="p-2">
                            No tables or columns match “{query}”
                        </Text>
                    }
                />
            </div>
        )
    },
}

const MANY: FileNode[] = Array.from({ length: 50 }, (_, folder) => ({
    id: `folder-${folder}`,
    textValue: `folder-${folder}`,
    children: Array.from({ length: 99 }, (_, file) => ({
        id: `folder-${folder}/file-${file}`,
        textValue: `file-${file}.json`,
    })),
}))

export const Virtualized: Story = {
    name: 'Virtualized 5,000 rows',
    render: () => (
        <ControlledTree
            items={MANY}
            virtualized
            defaultExpandedIds={MANY.map((node) => node.id)}
            renderItem={renderFile}
        />
    ),
}

export const EmptyTree: Story = {
    name: 'Empty',
    render: () => (
        <ControlledTree
            items={[] as FileNode[]}
            renderItem={renderFile}
            empty={
                <Text size="xs" variant="muted" className="p-2">
                    No files yet
                </Text>
            }
        />
    ),
}
