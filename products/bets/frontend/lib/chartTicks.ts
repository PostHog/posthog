export function chartTicks(labels: string[], format: (label: string) => string): string[] {
    if (!labels.length) {
        return []
    }
    const first = format(labels[0])
    const last = format(labels[labels.length - 1])
    return first === last ? ['', last] : [first, last]
}
