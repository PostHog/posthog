import { IconDatabase, IconDocument } from '@posthog/icons'

import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { NotebookKernelFrame } from '../../Notebook/notebookKernelInfoLogic'
import { NotebookFrameNodeSummary } from '../notebookNodeContent'

export const DATAFRAMES_FOLDER_ID = 'notebook-dataframes'

// These render as tooltips on a row in *another* cell's sidebar, so they can't say "this cell"
// — that already means "the cell you're in" on the run controls, and would point at the wrong
// one for every row but the current cell's own output.
const NEVER_RAN_REASON = 'Run the cell that creates it to make it available'
const NO_FRAME_REASON = "The last run of the cell that creates it didn't produce a dataframe"
const NOT_IN_KERNEL_REASON = 'Not in the kernel right now. Run the cell that creates it to make it available'

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
 * One entry per name. Python cells deliberately don't disambiguate their names — they are the
 * raw kernel variables, where a repeated name means last-run-wins — and they default to `df`,
 * so two un-run Python cells is enough to produce the same name twice. Collapsing to the last
 * matches what the kernel actually holds, and keeps the tree's item ids unique.
 */
const dedupeByName = (entries: DataframeEntry[]): DataframeEntry[] => {
    const byName = new Map<string, DataframeEntry>()
    entries.forEach((entry) => byName.set(entry.name, entry))
    return [...byName.values()]
}

/**
 * The tree renders `row_count` as a plain count, so an estimate can't go through it honestly —
 * DuckDB's `estimated_size` doesn't track deletes and can read 100,000 for a table holding 10.
 * A DDL table therefore lists without a count rather than with a confident wrong one.
 */
const kernelEntry = (frame: NotebookKernelFrame): DataframeEntry => ({
    name: frame.name,
    columns: frame.columns,
    rowCount: frame.row_count_is_estimate ? null : frame.row_count,
    isTable: frame.kind !== 'frame',
})

/**
 * Drop cells that bind nothing worth showing: an empty one nobody has written yet holds no query
 * and no result, and its name is only the default. Listing those means every blank cell you add
 * spawns a greyed-out row (`sql_df_2`, `sql_df_3`, …) for a frame that was never conceived of.
 * A cell with a query but no run is different — it is a real intent to bind that name.
 */
const listableNodes = (nodes: NotebookFrameNodeSummary[]): NotebookFrameNodeSummary[] =>
    nodes.filter((node) => node.hasRun || node.code.trim())

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
function mergeEntries(nodes: NotebookFrameNodeSummary[], kernelFrames: NotebookKernelFrame[]): DataframeEntry[] {
    const kernelByName = new Map(kernelFrames.map((frame) => [frame.name, frame]))
    const listable = listableNodes(nodes)
    const boundByCell = new Set(listable.map((node) => node.name))

    const fromNodes = listable.map((node): DataframeEntry => {
        const kernelFrame = kernelByName.get(node.name)
        if (kernelFrame) {
            // The kernel holds it, so prefer its shape: that reflects the frame as it is now,
            // while the cell's stored result is only as fresh as that cell's last run.
            return kernelEntry(kernelFrame)
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
    const kernelOnly = kernelFrames.filter((frame) => !boundByCell.has(frame.name)).map(kernelEntry)

    return dedupeByName([...fromNodes, ...kernelOnly])
}

// Frame and column ids share one namespace, so the separator must be something an identifier
// can't contain — `-` would let a frame named `a-col-b` collide with column `b` of frame `a`.
const frameId = (index: number): string => `nb-frame:${index}`

const entryNode = (entry: DataframeEntry, index: number): TreeDataItem => ({
    id: frameId(index),
    name: entry.name,
    type: 'node',
    icon: entry.isTable ? <IconDatabase /> : <IconDocument />,
    disabledReason: entry.disabledReason,
    record: {
        type: 'notebook-frame',
        // QueryDatabase renders this natively next to the name, the same as a warehouse table's.
        row_count: entry.rowCount ?? undefined,
    },
    children: entry.columns.map(([columnName, columnType], columnIndex) => ({
        id: `${frameId(index)}:col:${columnIndex}`,
        name: columnName,
        type: 'node' as const,
        // The shape QueryDatabase's renderItem expects for a column: monospaced name plus a
        // muted type suffix, so a dataframe's columns read like a table's. Only the rendering
        // is shared — its click handler needs `table`/`columnName`, which a kernel frame has no
        // equivalent of, so selection is disabled rather than left as a click that does nothing.
        record: { type: 'column', field: { name: columnName, type: columnType } },
        disableSelect: true,
    })),
})

/**
 * The "Dataframes" section for the SQLV2 node's schema browser: the names this notebook's cells
 * bind, plus anything extra its kernel holds. A name that can't be referenced as things stand
 * renders greyed out rather than disappearing — a cell you can see in the notebook going missing
 * from the browser is more confusing than one shown as unavailable.
 *
 * Unfiltered: QueryDatabase applies its own search term to these sections, so this stays out of
 * queryDatabaseLogic (reading it would mount its warehouse loaders in every notebook).
 */
export function buildDataframeTreeSection(
    nodes: NotebookFrameNodeSummary[],
    kernelFrames: NotebookKernelFrame[]
): TreeDataItem[] {
    const entries = mergeEntries(nodes, kernelFrames)
    if (!entries.length) {
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
            children: entries.map(entryNode),
        },
    ]
}
