import type { BlockPropValue, BlockPropsRecord } from '../../../editing/blockLibrary/blockDefinitions'

export type BlockPropsChange = (props: BlockPropsRecord) => void

export function asString(value: unknown, fallback = ''): string {
    return typeof value === 'string' ? value : fallback
}

export function asStrings(value: unknown, fallback: string[]): string[] {
    return Array.isArray(value) && value.every((item) => typeof item === 'string') ? value : fallback
}

export function asNumber(value: unknown, fallback: number): number {
    return typeof value === 'number' ? value : fallback
}

export function asBoolean(value: unknown, fallback: boolean): boolean {
    return typeof value === 'boolean' ? value : fallback
}

/** The props an author can change. The block id ties the block to its source, so it never shows. */
export function editableProps(props: Record<string, unknown>): BlockPropsRecord {
    const result: BlockPropsRecord = {}
    for (const [key, value] of Object.entries(props)) {
        if (key !== 'blockId') {
            result[key] = value as BlockPropValue
        }
    }
    return result
}
