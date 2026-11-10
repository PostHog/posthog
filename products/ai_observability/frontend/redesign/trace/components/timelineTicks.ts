const MAX_INTERVALS = 5
const NICE_MANTISSAS = [1, 2, 5]
// The end label sits right-aligned at 100%, so a tick this close to the end would overlap it.
const END_LABEL_CLEARANCE = 0.15

export interface TimelineTick {
    valueMs: number
    fraction: number
}

function niceStepMs(totalMs: number): number {
    const minimumStep = Math.max(totalMs / MAX_INTERVALS, 1)
    let magnitude = 10 ** Math.floor(Math.log10(minimumStep))
    for (;;) {
        for (const mantissa of NICE_MANTISSAS) {
            if (mantissa * magnitude >= minimumStep) {
                return mantissa * magnitude
            }
        }
        magnitude *= 10
    }
}

export function timelineTicks(totalMs: number): TimelineTick[] {
    if (totalMs <= 0) {
        return [{ valueMs: 0, fraction: 0 }]
    }
    const stepMs = niceStepMs(totalMs)
    const ticks: TimelineTick[] = []
    for (let valueMs = 0; valueMs / totalMs <= 1 - END_LABEL_CLEARANCE; valueMs += stepMs) {
        ticks.push({ valueMs, fraction: valueMs / totalMs })
    }
    return ticks
}
