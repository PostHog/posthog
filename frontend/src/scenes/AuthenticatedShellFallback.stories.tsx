import { Meta } from '@storybook/react'

import { markChunkFailureReload } from 'lib/utils/chunkReloadGuard'

import { AuthenticatedShellFallback } from './AuthenticatedShellFallback'

const meta: Meta<typeof AuthenticatedShellFallback> = {
    title: 'Scenes-Other/AuthenticatedShellFallback',
    component: AuthenticatedShellFallback,
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            // The fallback is itself a loader, so never wait for the spinner to disappear.
            waitForLoadersToDisappear: false,
            // Wait past the retry delay so the snapshot captures the explained, actionable state.
            waitForSelector: '[data-attr="authenticated-shell-fallback-reload"]',
            waitForSelectorTimeout: 12000,
        },
    },
}
export default meta

export function StuckShell(): JSX.Element {
    // Stamp the shared reload guard, so the fallback shows the prompt a person gets after the
    // automatic reload instead of reloading the Storybook page.
    markChunkFailureReload()
    return <AuthenticatedShellFallback showSpinner />
}
