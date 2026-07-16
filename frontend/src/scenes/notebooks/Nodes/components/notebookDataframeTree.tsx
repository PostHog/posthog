import { IconDatabase, IconDocument } from '@posthog/icons'

import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { NotebookKernelFrame } from '../../Notebook/notebookKernelInfoLogic'

export const DATAFRAMES_FOLDER_ID = 'notebook-dataframes'

const KIND_LABEL: Record<NotebookKernelFrame['kind'], string> = {
    frame: 'dataframe',
    table: 'table',
    view: 'view',
}

const matchesSearch = (frame: NotebookKernelFrame, needle: string): boolean =>
    frame.name.toLowerCase().includes(needle) ||
    frame.columns.some(([columnName]) => columnName.toLowerCase().includes(needle))

const frameNode = (frame: NotebookKernelFrame): TreeDataItem => ({
    id: `nb-frame-${frame.name}`,
    name: frame.name,
    type: 'node',
    icon: frame.kind === 'frame' ? <IconDocument /> : <IconDatabase />,
    record: {
        type: 'notebook-frame',
        // QueryDatabase renders this natively next to the name, the same as a warehouse table's.
        row_count: frame.row_count ?? undefined,
        kindLabel: KIND_LABEL[frame.kind],
    },
    children: frame.columns.map(([columnName, columnType]) => ({
        id: `nb-frame-${frame.name}-col-${columnName}`,
        name: columnName,
        type: 'node' as const,
        // The shape QueryDatabase's renderItem expects for a column: monospaced name plus a
        // muted type suffix. Reused so a dataframe's columns read exactly like a table's.
        record: { type: 'column', field: { name: columnName, type: columnType } },
    })),
})

/**
 * The "Dataframes" section for the SQLV2 node's schema browser: what this notebook's kernel can
 * currently SELECT from. Empty when no kernel is live — nothing local is queryable without one,
 * so there is nothing honest to show.
 *
 * `searchTerm` is the database tree's own, read from queryDatabaseLogic: the tree swaps in its
 * filtered data while searching, so an unfiltered section would sit above the results ignoring
 * the query.
 */
export function buildDataframeTreeSection(frames: NotebookKernelFrame[], searchTerm: string): TreeDataItem[] {
    if (!frames.length) {
        return []
    }
    const needle = searchTerm.trim().toLowerCase()
    const matching = needle ? frames.filter((frame) => matchesSearch(frame, needle)) : frames
    if (!matching.length) {
        return []
    }
    return [
        {
            id: DATAFRAMES_FOLDER_ID,
            name: 'Dataframes',
            // Bold like the built-in section headers, which key off record types we don't share.
            displayName: <span className="font-semibold">Dataframes</span>,
            type: 'node',
            icon: <IconDatabase />,
            record: { type: 'notebook-dataframes' },
            children: matching.map(frameNode),
        },
    ]
}
