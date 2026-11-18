import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { extensionAuthLogic } from '../../logics/panel/extensionAuthLogic'
import { ExtensionPageToolbarTools } from './ExtensionPageToolbarTools'

export function ExtensionPageToolbar(): JSX.Element {
    const { authStatus } = useValues(extensionAuthLogic)
    const { authenticate } = useActions(extensionAuthLogic)

    if (authStatus === 'authenticated') {
        return <ExtensionPageToolbarTools />
    }
    if (authStatus === 'signed-out' || authStatus === 'failed') {
        return (
            <LemonBanner
                type={authStatus === 'failed' ? 'warning' : 'info'}
                action={{
                    children: 'Connect',
                    onClick: () => authenticate(true),
                    'data-attr': 'toolbar-extension-connect',
                }}
            >
                {authStatus === 'failed'
                    ? "Couldn't connect the toolbar to this project. Connect again, and finish any step PostHog shows in the new tab."
                    : 'Connect the toolbar to this project to use its tools on this page.'}
            </LemonBanner>
        )
    }
    return (
        <div className="flex items-center gap-2 text-secondary text-xs">
            <Spinner />
            Connecting the toolbar to this project…
        </div>
    )
}
