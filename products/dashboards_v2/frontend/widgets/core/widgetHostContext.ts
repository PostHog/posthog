import { createContext } from 'react'

export type QueryOutcome = 'success' | 'error'

/** Told when a widget's query starts. The function it returns is called once the query ends. */
export type QueryTiming = {
    started: (cached: boolean) => (outcome: QueryOutcome) => void
    /** Keeps the load open, such as while a widget's code downloads. The function it returns lets it end again. */
    hold: () => () => void
}

export type WidgetHost = {
    /** A widget that loads data loads it again when this changes. */
    refresh: number
    /** True while the host has no real data, such as in a project with no events. Widgets show their `SampleData` part and run no queries. */
    sampleData: boolean
    timing: QueryTiming | null
}

/** What the host passes down to every widget. A widget rendered on its own gets the defaults and works the same way. */
export const WidgetHostContext = createContext<WidgetHost>({ refresh: 0, sampleData: false, timing: null })
