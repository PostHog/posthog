import type { ReactNode } from 'react'

import { lazyWithRetry } from 'lib/utils/retryImport'

import { loadCoreFilterDefinitions } from './loadCoreFilterDefinitions'

function Loaded({ children }: { children: ReactNode }): JSX.Element {
    return <>{children}</>
}

/**
 * Suspends its children until the taxonomy loads. Label helpers read the taxonomy without subscribing to it,
 * so a panel that renders before the first scene does would otherwise keep its raw keys.
 */
export const CoreFilterDefinitionsGate = lazyWithRetry(() =>
    loadCoreFilterDefinitions().then(() => ({ default: Loaded }))
)
