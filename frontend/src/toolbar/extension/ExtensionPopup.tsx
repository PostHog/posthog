import { useActions, useValues } from 'kea'

import { IconLogomark } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { urls } from '~/toolbar/urls'

import { canRequestHostPermission, isDevtoolsPanel } from './extensionBrowser'
import { ExtensionFeatureList } from './ExtensionFeatureList'
import { ExtensionPageTools } from './ExtensionPageTools'
import { extensionPopupLogic } from './extensionPopupLogic'
import { ExtensionPopupSettings } from './ExtensionPopupSettings'
import type { ExtensionPopupState, UnsupportedPageReason } from './extensionPopupState'

const UNSUPPORTED_PAGE_MESSAGES: Record<UnsupportedPageReason, string> = {
    'browser-page': "The toolbar can't run on this page. Open your website to use it.",
    'insecure-page': 'The toolbar needs a secure page. Open the https version of this site.',
    'posthog-app': 'This is the PostHog app. Open your website to use the toolbar.',
    'extension-store': "Browsers don't let extensions run on this page. Open your website to use the toolbar.",
}

function ExtensionPopupBody({ popupState }: { popupState: ExtensionPopupState }): JSX.Element {
    const { uiHost, user } = useValues(extensionPopupLogic)
    const { requestHostPermission, openPostHogPath, retry } = useActions(extensionPopupLogic)
    const host = new URL(uiHost).host
    const projectName = user?.team.name ?? 'this project'

    switch (popupState.kind) {
        case 'checking':
            return (
                <div className="flex items-center gap-2 text-secondary">
                    <Spinner />
                    Checking access…
                </div>
            )
        case 'unsupported-page':
            return <LemonBanner type="info">{UNSUPPORTED_PAGE_MESSAGES[popupState.reason]}</LemonBanner>
        case 'host-permission-needed':
            if (!canRequestHostPermission()) {
                return (
                    <LemonBanner type="info">
                        Open the extension popup and allow access to {host}, then open DevTools again.
                    </LemonBanner>
                )
            }
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
                    Log in to PostHog on {host}, then open this popup again.
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
                        onClick: () =>
                            openPostHogPath(
                                `/project/${user?.team.id}${urls.settings('project-toolbar', 'authorized-urls')}`
                            ),
                        'data-attr': 'toolbar-extension-authorized-urls',
                    }}
                >
                    {popupState.origin} isn't an authorized URL for {projectName}. Add it to use the toolbar here.
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
            return (
                <>
                    <ExtensionPageTools />
                    <ExtensionFeatureList origin={popupState.origin} />
                </>
            )
    }
}

export function ExtensionPopup(): JSX.Element {
    const { popupState } = useValues(extensionPopupLogic)

    return (
        <div className={`flex flex-col gap-3 p-3 ${isDevtoolsPanel() ? 'w-full max-w-xl' : 'w-80'}`}>
            <div className="flex items-center gap-2 font-semibold">
                <IconLogomark className="text-xl" />
                PostHog toolbar
            </div>
            <ExtensionPopupBody popupState={popupState} />
            <ExtensionPopupSettings />
        </div>
    )
}
