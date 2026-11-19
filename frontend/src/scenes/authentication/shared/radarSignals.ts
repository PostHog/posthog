import { WorkOSRadar } from '@workos/radar-signals'

// WorkOS accepts a token for one hour after collection, so this keeps a margin under that hour
const RADAR_SIGNALS_MAX_AGE_MS = 55 * 60 * 1000

let radar: WorkOSRadar | null = null
let startedAt = 0
let sentToken = ''

/** Loads the WorkOS Radar browser script, which collects device signals while the person types. */
export function startRadarSignals(clientId: string): void {
    if (radar) {
        return
    }
    try {
        radar = WorkOSRadar.init({ clientId })
        startedAt = Date.now()
    } catch {
        radar = null
    }
}

/** The script makes one token per page load and WorkOS links each token to one attempt, so a sent or old token gives ''. */
export async function getRadarSignalsId(): Promise<string> {
    if (!radar) {
        return ''
    }
    try {
        const token = await radar.getToken()
        if (token === sentToken || Date.now() - startedAt > RADAR_SIGNALS_MAX_AGE_MS) {
            return ''
        }
        return token
    } catch {
        return ''
    }
}

export function markRadarSignalsIdSent(token: string): void {
    sentToken = token
}
