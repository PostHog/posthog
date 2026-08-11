export const AXIS_TICK_LABEL_HEIGHT = 14

const MAX_TICK_LABEL_ROTATION = 90
const ROTATED_TICK_LABEL_PADDING = 4

export function normalizeAxisLabel(label: string | null | undefined): string | undefined {
    const trimmed = label?.trim()
    return trimmed ? trimmed : undefined
}

export function normalizeTickLabelRotation(rotation = 0): number {
    if (!Number.isFinite(rotation)) {
        return 0
    }
    return Math.max(-MAX_TICK_LABEL_ROTATION, Math.min(MAX_TICK_LABEL_ROTATION, rotation))
}

export function rotatedTickLabelSize(width: number, rotation: number): { width: number; height: number } {
    const radians = (Math.abs(normalizeTickLabelRotation(rotation)) * Math.PI) / 180
    const sin = Math.sin(radians)
    const cos = Math.cos(radians)
    return {
        width: width * cos + AXIS_TICK_LABEL_HEIGHT * sin,
        height: width * sin + AXIS_TICK_LABEL_HEIGHT * cos,
    }
}

export function minimumRotatedTickLabelGap(rotation: number): number {
    const radians = (Math.abs(normalizeTickLabelRotation(rotation)) * Math.PI) / 180
    if (radians === 0) {
        return 0
    }
    return Math.ceil((AXIS_TICK_LABEL_HEIGHT + ROTATED_TICK_LABEL_PADDING) / Math.sin(radians))
}
