export interface TooltipMountStats {
    active: number
    peak: number
    totalMounts: number
    totalUnmounts: number
}

let active = 0
let peak = 0
let totalMounts = 0
let totalUnmounts = 0

declare global {
    interface Window {
        __posthogTooltipStats?: () => TooltipMountStats
    }
}

export function trackTooltipMount(): void {
    active++
    totalMounts++
    if (active > peak) {
        peak = active
    }
}

export function trackTooltipUnmount(): void {
    active--
    totalUnmounts++
}

export function getTooltipStats(): TooltipMountStats {
    return { active, peak, totalMounts, totalUnmounts }
}

if (typeof window !== 'undefined') {
    window.__posthogTooltipStats = getTooltipStats
}
