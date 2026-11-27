import { createContext } from 'react'

// `aborted` means the panel stopped waiting, such as when it unmounted, so it does not count as a failure.
export type QueryOutcome = 'success' | 'error' | 'aborted'

/** Told when a panel's query starts. The function it returns is called once the query ends. */
export type QueryTiming = {
    started: (cached: boolean) => (outcome: QueryOutcome) => void
    /** Keeps the load open, such as while a panel's code downloads. The function it returns lets it end again. */
    hold: () => () => void
}

export type PanelHost = {
    /** A panel that loads data loads it again when this changes. */
    refresh: number
    timing: QueryTiming | null
}

/** What the host passes down to every panel. A panel rendered on its own gets the defaults and works the same way. */
export const PanelHostContext = createContext<PanelHost>({ refresh: 0, timing: null })
