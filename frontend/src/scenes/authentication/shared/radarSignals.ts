import { WorkOSRadar } from '@workos/radar-signals'

let radar: WorkOSRadar | null = null

/** Loads the WorkOS Radar browser script, which collects device signals while the person types. */
export function startRadarSignals(clientId: string): void {
    if (radar) {
        return
    }
    try {
        radar = WorkOSRadar.init({ clientId })
    } catch {
        radar = null
    }
}

/** The token that links this browser's signals to a login, or '' when the script did not load. */
export async function getRadarSignalsId(): Promise<string> {
    if (!radar) {
        return ''
    }
    try {
        return await radar.getToken()
    } catch {
        return ''
    }
}
