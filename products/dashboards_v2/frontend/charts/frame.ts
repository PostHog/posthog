export type FieldType = 'time' | 'number' | 'string' | 'boolean' | 'other'

export interface Field {
    name: string
    type: FieldType
    values: unknown[]
    labels?: Record<string, string>
    config?: { unit?: string; displayName?: string }
}

export interface DataFrame {
    name?: string
    refId?: string
    fields: Field[]
    meta?: {
        executedQuery?: string
        rows?: number
        tookMs?: number
        previous?: boolean
        asOf?: number
    }
}

export function asPrevious(frames: DataFrame[]): DataFrame[] {
    return frames.map((frame) => {
        if (frame.meta?.previous) {
            return frame
        }
        const numbers = frame.fields.filter((field) => field.type === 'number')
        const meta = { ...frame.meta, previous: true }
        if (numbers.length <= 1 || frame.name) {
            const name = frame.name ?? numbers[0]?.config?.displayName ?? numbers[0]?.name ?? 'value'
            return { ...frame, name: `${name} (previous)`, meta }
        }
        return {
            ...frame,
            fields: frame.fields.map((field) =>
                field.type === 'number'
                    ? {
                          ...field,
                          config: {
                              ...field.config,
                              displayName: `${field.config?.displayName ?? field.name} (previous)`,
                          },
                      }
                    : field
            ),
            meta,
        }
    })
}
