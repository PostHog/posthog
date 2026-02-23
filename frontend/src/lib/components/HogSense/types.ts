export interface GuidanceDoc {
    label: string
    url: string
    mono?: boolean
}

export type HogSenseSeverity = 'info' | 'warning' | 'error'

export interface DetectionEntry<T> {
    id: string
    trigger: (context: T) => boolean
    summary: string
    description: string
    severity: HogSenseSeverity
    docs?: GuidanceDoc[]
}

export interface Finding {
    id: string
    summary: string
    description: string
    severity: HogSenseSeverity
    docs?: GuidanceDoc[]
    entityType?: string
    entityId?: string | number
}
