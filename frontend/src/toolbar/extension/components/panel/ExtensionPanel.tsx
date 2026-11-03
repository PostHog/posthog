import { useActions, useValues } from 'kea'

import { Logo } from 'lib/brand'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { urls } from '~/toolbar/shared/urls'

import { extensionPanelLogic } from '../../logics/panel/extensionPanelLogic'
import type { ExtensionPanelState, UnsupportedPageReason } from '../../logics/panel/extensionPanelState'
import { ExtensionPageToolbar } from './ExtensionPageToolbar'
import { ExtensionPanelSettings } from './ExtensionPanelSettings'

const UNSUPPORTED_PAGE_MESSAGES: Record<UnsupportedPageReason, string> = {
    'browser-page': "The toolbar can't run on this page. Open your website to use it.",
    'insecure-page': 'The toolbar needs a secure page. Open the https version of this site.',
    'posthog-app': 'This is the PostHog app. Open your website to use the toolbar.',
    'extension-store': "Browsers don't let extensions run on this page. Open your website to use the toolbar.",
}

function ExtensionPanelBody({ panelState }: { panelState: ExtensionPanelState }): JSX.Element {
    const { uiHost, user } = useValues(extensionPanelLogic)
    const { requestHostPermission, openPostHogPath, openProjectPath, retry } = useActions(extensionPanelLogic)
    const host = new URL(uiHost).host
    const projectName = user?.team.name ?? 'this project'

    switch (panelState.kind) {
        case 'checking':
            return (
                <div className="flex items-center gap-2 text-secondary">
                    <Spinner />
                    Checking access…
                </div>
            )
        case 'unsupported-page':
            return <LemonBanner type="info">{UNSUPPORTED_PAGE_MESSAGES[panelState.reason]}</LemonBanner>
        case 'host-permission-needed':
            return (
                <LemonBanner
                    type="info"
                    action={{
                        children: 'Allow access',
                        onClick: requestHostPermission,
                        'data-attr': 'toolbar-extension-allow-host',
                    }}
                >
                    Allow the extension to use your PostHog login on {host}.
                </LemonBanner>
            )
        case 'signed-out':
            return (
                <LemonBanner
                    type="info"
                    action={{
                        children: 'Log in',
                        onClick: () => openPostHogPath('/login'),
                        'data-attr': 'toolbar-extension-log-in',
                    }}
                >
                    Log in to PostHog on {host}, then come back to this tab.
                </LemonBanner>
            )
        case 'no-toolbar-access':
            return (
                <LemonBanner type="warning">
                    You don't have toolbar access in {projectName}. Ask a project admin for access, or switch to another
                    project.
                </LemonBanner>
            )
        case 'unauthorized-url':
            return (
                <LemonBanner
                    type="warning"
                    action={{
                        children: 'Open authorized URLs',
                        onClick: () => openProjectPath(urls.settings('project-toolbar', 'authorized-urls')),
                        'data-attr': 'toolbar-extension-authorized-urls',
                    }}
                >
                    {panelState.origin} isn't an authorized URL for {projectName}. Add it to use the toolbar here.
                </LemonBanner>
            )
        case 'error':
            return (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: retry, 'data-attr': 'toolbar-extension-retry' }}
                >
                    Couldn't reach PostHog on {host}. Check your connection and try again.
                </LemonBanner>
            )
        case 'ready':
            return <ExtensionPageToolbar />
    }
}

export function ExtensionPanel(): JSX.Element {
    const { panelState } = useValues(extensionPanelLogic)

    return (
        <div className="flex min-h-screen flex-col gap-3 p-3">
            <h1 className="m-0 flex">
                <Logo size="xs" title="PostHog" />
            </h1>
            <ExtensionPanelBody panelState={panelState} />
            <ExtensionPanelSettings />
        </div>
    )
}
