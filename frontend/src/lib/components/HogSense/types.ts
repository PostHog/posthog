export interface GuidanceDoc {
    label: string
    url: string
    mono?: boolean
}

export type HogSenseSeverity = 'info' | 'warning' | 'error'

/** Detection layer: just a trigger with an ID and severity. No content. */
export interface DetectionEntry<T> {
    id: string
    trigger: (context: T) => boolean
    severity: HogSenseSeverity
}

/** Raw output of running detections — what fired and at what severity. */
export interface DetectionResult {
    id: string
    severity: HogSenseSeverity
    entityType?: string
    entityId?: string | number
}

/** Knowledge layer: human-readable content keyed by detection ID. */
export interface KnowledgeEntry {
    summary: string
    description: string
    docs?: GuidanceDoc[]
}

/** Resolved finding: detection result enriched with knowledge. Ready for rendering. */
export interface Finding {
    id: string
    summary: string
    description: string
    severity: HogSenseSeverity
    docs?: GuidanceDoc[]
    entityType?: string
    entityId?: string | number
}

export type HogSenseDisplay = 'banner' | 'hint'

export interface HogSenseRenderEntry {
    ids: readonly string[]
    display: HogSenseDisplay
    className?: string
}

export type HogSenseRenderMap = Record<string, HogSenseRenderEntry[]>
