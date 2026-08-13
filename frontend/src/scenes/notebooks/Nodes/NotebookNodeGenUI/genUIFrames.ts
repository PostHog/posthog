import { JSONContent } from 'lib/components/RichContentEditor/types'

import { collectNotebookFrameNodes } from '../notebookNodeContent'

const MAX_FRAME_COLUMNS = 100
const MAX_FRAME_COUNT = 4
const MAX_FRAME_ROWS = 100
const MAX_FRAME_BYTES = 200 * 1024
const MAX_CELL_STRING_LENGTH = 4096
const MAX_COLUMN_METADATA_LENGTH = 256
const MAX_FRAME_NAME_LENGTH = 128
const FRAME_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/

export type GenUIFrame = {
    name: string
    columns: { name: string; type: string }[]
    rows: unknown[][]
    totalRowCount: number
    includedRowCount: number
    truncated: boolean
}

export type GenUIFrameSchema = Pick<GenUIFrame, 'name' | 'columns' | 'totalRowCount' | 'includedRowCount' | 'truncated'>

export function parseGenUIInputNames(inputs: string): string[] {
    return Array.from(
        new Set(
            inputs
                .split(/[\s,]+/)
                .map((name) => name.trim())
                .filter((name) => name.length <= MAX_FRAME_NAME_LENGTH && FRAME_NAME.test(name))
        )
    ).slice(0, MAX_FRAME_COUNT)
}

function safeCellValue(value: unknown): unknown {
    if (value === null || typeof value === 'number' || typeof value === 'boolean') {
        return value
    }
    if (typeof value === 'string') {
        return value.slice(0, MAX_CELL_STRING_LENGTH)
    }
    try {
        const serialized = JSON.stringify(value)
        return typeof serialized === 'string'
            ? serialized.slice(0, MAX_CELL_STRING_LENGTH)
            : String(value).slice(0, MAX_CELL_STRING_LENGTH)
    } catch {
        return String(value).slice(0, MAX_CELL_STRING_LENGTH)
    }
}

export function buildGenUIFrames(content: JSONContent | null | undefined, inputs: string): Record<string, GenUIFrame> {
    const requestedNames = new Set(parseGenUIInputNames(inputs))
    const frames: Record<string, GenUIFrame> = {}

    for (const node of collectNotebookFrameNodes(content)) {
        if (!requestedNames.has(node.name) || !node.hasRun) {
            continue
        }

        const columns = node.columns.slice(0, MAX_FRAME_COLUMNS).map(([name, type]) => ({
            name: name.slice(0, MAX_COLUMN_METADATA_LENGTH),
            type: type.slice(0, MAX_COLUMN_METADATA_LENGTH),
        }))
        const totalRowCount = node.rowCount ?? node.previewRows?.length ?? 0
        const rows: unknown[][] = []

        for (const rawRow of (node.previewRows ?? []).slice(0, MAX_FRAME_ROWS)) {
            const row = rawRow.slice(0, columns.length).map(safeCellValue)
            const candidateRows = [...rows, row]
            const candidate: GenUIFrame = {
                name: node.name,
                columns,
                rows: candidateRows,
                totalRowCount,
                includedRowCount: candidateRows.length,
                truncated: candidateRows.length < totalRowCount,
            }
            if (JSON.stringify(candidate).length > MAX_FRAME_BYTES) {
                break
            }
            rows.push(row)
        }

        frames[node.name] = {
            name: node.name,
            columns,
            rows,
            totalRowCount,
            includedRowCount: rows.length,
            truncated: rows.length < totalRowCount,
        }
    }

    return frames
}

export function getGenUIFrameSchemas(
    content: JSONContent | null | undefined,
    inputs: string
): { schemas: GenUIFrameSchema[]; missing: string[] } {
    const requestedNames = parseGenUIInputNames(inputs)
    const frames = buildGenUIFrames(content, inputs)
    return {
        schemas: requestedNames.flatMap((name) => {
            const frame = frames[name]
            if (!frame) {
                return []
            }
            return [
                {
                    name: frame.name,
                    columns: frame.columns,
                    totalRowCount: frame.totalRowCount,
                    includedRowCount: frame.includedRowCount,
                    truncated: frame.truncated,
                },
            ]
        }),
        missing: requestedNames.filter((name) => !frames[name]),
    }
}
