import { IconDatabase, IconDocument } from '@posthog/icons'

import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { NotebookKernelFrame } from '../../Notebook/notebookKernelInfoLogic'
import { NotebookFrameNodeSummary } from '../notebookNodeContent'

export const DATAFRAMES_FOLDER_ID = 'notebook-dataframes'

const NEVER_RAN_REASON = 'Run this cell to make it available'
const NO_FRAME_REASON = "This cell's last run didn't produce a dataframe"
const NOT_IN_KERNEL_REASON = 'Not in the kernel right now — run this cell to make it available'

type DataframeEntry = {
    name: string
    columns: [string, string][]
    rowCount: number | null
    /** A DuckDB table or view reads differently from a dataframe, so they get different icons. */
    isTable: boolean
    /** Set when the name can't be referenced as things stand; renders greyed out with this reason. */
    disabledReason?: string
}

/**
 * Merge what the notebook knows with what the kernel knows. Neither is sufficient alone:
 *
 * - The kernel's catalog is the only thing that can see a table a DuckDB cell created, and the
 *   only honest answer to whether a Python cell's frame still exists.
 * - It cannot see a SQL cell's output, though. That output lives in ClickHouse and only enters
 *   the kernel if some cell materializes it — yet it stays referenceable from SQL the whole
 *   time, re-inlined as a CTE. Listing the kernel's view alone makes a SQL frame appear or
 *   vanish depending on whether an unrelated Python cell happens to use it.
 */
/**
 * Drop cells that bind nothing worth showing: an empty one nobody has written yet holds no query
 * and no result, and its name is only the default. Listing those means every blank cell you add
 * spawns a greyed-out row (`sql_df_2`, `sql_df_3`, …) for a frame that was never conceived of.
 * A cell with a query but no run is different — it is a real intent to bind that name.
 */
const listableNodes = (nodes: NotebookFrameNodeSummary[]): NotebookFrameNodeSummary[] =>
    nodes.filter((node) => node.hasRun || node.code.trim())

function mergeEntries(nodes: NotebookFrameNodeSummary[], kernelFrames: NotebookKernelFrame[]): DataframeEntry[] {
    const kernelByName = new Map(kernelFrames.map((frame) => [frame.name, frame]))
    const boundByCell = new Set(listableNodes(nodes).map((node) => node.name))

    const fromNodes = listableNodes(nodes).map((node): DataframeEntry => {
        const kernelFrame = kernelByName.get(node.name)
        if (kernelFrame) {
            // The kernel holds it, so prefer its shape: that reflects the frame as it is now,
            // while the cell's stored result is only as fresh as that cell's last run.
            return {
                name: node.name,
                columns: kernelFrame.columns,
                rowCount: kernelFrame.row_count,
                isTable: kernelFrame.kind !== 'frame',
            }
        }
        const base = { name: node.name, columns: node.columns, rowCount: node.rowCount, isTable: false }
        if (!node.hasRun) {
            return { ...base, disabledReason: NEVER_RAN_REASON }
        }
        if (!node.columns.length) {
            // It ran and bound nothing — its code produces no frame, or it was DDL. Telling the
            // user to run it would be a lie; running it again changes nothing.
            return { ...base, disabledReason: NO_FRAME_REASON }
        }
        // A SQL cell that ran is referenceable with no kernel at all; a Python cell's frame only
        // ever exists in the kernel, so its absence from the catalog means it is really gone.
        return node.nodeType === 'sql' ? base : { ...base, disabledReason: NOT_IN_KERNEL_REASON }
    })

    // Anything the kernel has that no cell binds: a table a DuckDB cell created with DDL, which
    // exists only in the kernel and is invisible to the notebook document.
    const kernelOnly = kernelFrames
        .filter((frame) => !boundByCell.has(frame.name))
        .map(
            (frame): DataframeEntry => ({
                name: frame.name,
                columns: frame.columns,
                rowCount: frame.row_count,
                isTable: frame.kind !== 'frame',
            })
        )

    return [...fromNodes, ...kernelOnly]
}

const matchesSearch = (entry: DataframeEntry, needle: string): boolean =>
    entry.name.toLowerCase().includes(needle) ||
    entry.columns.some(([columnName]) => columnName.toLowerCase().includes(needle))

const entryNode = (entry: DataframeEntry): TreeDataItem => ({
    id: `nb-frame-${entry.name}`,
    name: entry.name,
    type: 'node',
    icon: entry.isTable ? <IconDatabase /> : <IconDocument />,
    disabledReason: entry.disabledReason,
    record: {
        type: 'notebook-frame',
        // QueryDatabase renders this natively next to the name, the same as a warehouse table's.
        row_count: entry.rowCount ?? undefined,
    },
    children: entry.columns.map(([columnName, columnType]) => ({
        id: `nb-frame-${entry.name}-col-${columnName}`,
        name: columnName,
        type: 'node' as const,
        // The shape QueryDatabase's renderItem expects for a column: monospaced name plus a
        // muted type suffix. Reused so a dataframe's columns read exactly like a table's.
        record: { type: 'column', field: { name: columnName, type: columnType } },
    })),
})

/**
 * The "Dataframes" section for the SQLV2 node's schema browser: the names this notebook's cells
 * bind, plus anything extra its kernel holds. A name that can't be referenced as things stand
 * renders greyed out rather than disappearing — a cell you can see in the notebook going missing
 * from the browser is more confusing than one shown as unavailable.
 *
 * `searchTerm` is the database tree's own, read from queryDatabaseLogic: the tree swaps in its
 * filtered data while searching, so an unfiltered section would sit above the results ignoring
 * the query.
 */
export function buildDataframeTreeSection(
    nodes: NotebookFrameNodeSummary[],
    kernelFrames: NotebookKernelFrame[],
    searchTerm: string
): TreeDataItem[] {
    const entries = mergeEntries(nodes, kernelFrames)
    if (!entries.length) {
        return []
    }
    const needle = searchTerm.trim().toLowerCase()
    const matching = needle ? entries.filter((entry) => matchesSearch(entry, needle)) : entries
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
            children: matching.map(entryNode),
        },
    ]
}
