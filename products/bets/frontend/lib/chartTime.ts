import { dayjs } from 'lib/dayjs'

export function timeToX(at: string, labels: string[], x: (label: string) => number | undefined): number | null {
    const time = dayjs(at).valueOf()
    const moments = labels.map((label) => dayjs(label).valueOf())
    if (!labels.length || Number.isNaN(time) || moments.some(Number.isNaN)) {
        return null
    }
    const after = moments.findIndex((moment) => moment >= time)
    if (after <= 0) {
        return x(labels[after === 0 ? 0 : labels.length - 1]) ?? null
    }
    const start = x(labels[after - 1])
    const end = x(labels[after])
    if (start === undefined || end === undefined) {
        return null
    }
    const share = (time - moments[after - 1]) / (moments[after] - moments[after - 1] || 1)
    return start + (end - start) * share
}
