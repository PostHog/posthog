export type HealthBand = 'good' | 'ok' | 'bad' | 'unknown'

export function healthBand(score: number | null | undefined): HealthBand {
    if (score == null) {
        return 'unknown'
    }
    if (score >= 7) {
        return 'good'
    }
    if (score >= 5) {
        return 'ok'
    }
    return 'bad'
}

export function healthLabel(score: number | null | undefined): string {
    if (score == null) {
        return 'Unknown'
    }
    if (score >= 7) {
        return 'Healthy'
    }
    if (score >= 5) {
        return 'Watch'
    }
    if (score >= 3) {
        return 'At risk'
    }
    return 'Critical'
}
