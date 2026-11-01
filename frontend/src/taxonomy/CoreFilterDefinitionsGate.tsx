import type { ReactNode } from 'react'

import { retryImport } from 'lib/utils/retryImport'

import { loadCoreFilterDefinitions } from './loadCoreFilterDefinitions'
import { areCoreFilterDefinitionsLoaded } from './taxonomy'

let loadFailure: { error: unknown } | null = null

// Label helpers never re-render when the taxonomy arrives, so content that reads labels must wait for it.
export function CoreFilterDefinitionsGate({ children }: { children: ReactNode }): JSX.Element {
    if (loadFailure) {
        throw loadFailure.error
    }
    if (!areCoreFilterDefinitionsLoaded()) {
        throw retryImport(loadCoreFilterDefinitions).catch((error) => {
            loadFailure = { error }
        })
    }
    return <>{children}</>
}
