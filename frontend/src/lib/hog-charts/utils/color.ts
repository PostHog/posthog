export function hexToRgb(hex: string): [number, number, number] {
    const clean = hex.replace('#', '')
    if (clean.length === 3) {
        return [parseInt(clean[0] + clean[0], 16), parseInt(clean[1] + clean[1], 16), parseInt(clean[2] + clean[2], 16)]
    }
    return [parseInt(clean.slice(0, 2), 16), parseInt(clean.slice(2, 4), 16), parseInt(clean.slice(4, 6), 16)]
}

export function hexToRGBA(hex: string, alpha: number): string {
    const [r, g, b] = hexToRgb(hex)
    return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

export function lerpColor(a: string, b: string, t: number): string {
    const [ar, ag, ab] = hexToRgb(a)
    const [br, bg, bb] = hexToRgb(b)
    const r = Math.round(ar + (br - ar) * t)
    const g = Math.round(ag + (bg - ag) * t)
    const bl = Math.round(ab + (bb - ab) * t)
    return `rgb(${r}, ${g}, ${bl})`
}

export function interpolateColor(range: string[], value: number, min: number, max: number): string {
    if (max === min) {
        return range[range.length - 1]
    }
    const t = Math.max(0, Math.min(1, (value - min) / (max - min)))
    if (range.length === 2) {
        return lerpColor(range[0], range[1], t)
    }
    if (t <= 0.5) {
        return lerpColor(range[0], range[1], t * 2)
    }
    return lerpColor(range[1], range[2], (t - 0.5) * 2)
}
