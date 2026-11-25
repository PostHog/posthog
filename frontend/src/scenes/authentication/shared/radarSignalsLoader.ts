// The longest a submit waits for the Radar token, chunk download included, before it goes without one
const RADAR_SIGNALS_WAIT_MS = 3000

/** Loads the Radar browser script only when the server names a client, so a page downloads nothing extra while Radar is off. */
export function startRadarSignalsFor(clientId: string | null | undefined): void {
    if (!clientId) {
        return
    }
    void import('scenes/authentication/shared/radarSignals')
        .then(({ startRadarSignals }) => startRadarSignals(clientId))
        .catch(() => undefined)
}

async function radarSignalsIdFor(clientId: string | null | undefined): Promise<string> {
    if (!clientId) {
        return ''
    }
    const radarSignals = import('scenes/authentication/shared/radarSignals')
    const lookup = radarSignals.then(({ getRadarSignalsId }) => getRadarSignalsId()).catch(() => '')
    let timer: ReturnType<typeof setTimeout> | undefined
    const deadline = new Promise<string>((resolve) => {
        timer = setTimeout(() => resolve(''), RADAR_SIGNALS_WAIT_MS)
    })
    try {
        const radarSignalsId = await Promise.race([lookup, deadline])
        if (radarSignalsId) {
            // Marked only when the token goes out, so a token that arrives after the deadline is still sent with the next attempt
            const { markRadarSignalsIdSent } = await radarSignals
            markRadarSignalsIdSent(radarSignalsId)
        }
        return radarSignalsId
    } finally {
        clearTimeout(timer)
    }
}

export async function radarSignalsFields(clientId: string | null | undefined): Promise<{ radar_signals_id?: string }> {
    const radarSignalsId = await radarSignalsIdFor(clientId)
    return radarSignalsId ? { radar_signals_id: radarSignalsId } : {}
}
