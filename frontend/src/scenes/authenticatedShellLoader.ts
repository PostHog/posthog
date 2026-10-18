import { retryImport } from 'lib/utils/retryImport'

import type AuthenticatedShell from './AuthenticatedShell'

type AuthenticatedShellComponent = typeof AuthenticatedShell

let loadedAuthenticatedShell: AuthenticatedShellComponent | null = null

export function loadAuthenticatedShell(): Promise<AuthenticatedShellComponent> {
    return retryImport(() => import('./AuthenticatedShell')).then(({ default: shell }) => {
        loadedAuthenticatedShell = shell
        return shell
    })
}

export function getLoadedAuthenticatedShell(): AuthenticatedShellComponent | null {
    return loadedAuthenticatedShell
}
