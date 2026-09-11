import { useValues } from 'kea'
import { createPortal } from 'react-dom'

import { IconX } from '@posthog/icons'

import { Logomark } from 'lib/brand'
import { useFloatingContainer } from 'lib/hooks/useFloatingContainerContext'

import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

interface UiHostConfigModalProps {
    visible: boolean
    onClose: () => void
}

export function UiHostConfigModal({ visible, onClose }: UiHostConfigModalProps): JSX.Element | null {
    const { uiHostResolution, apiHostResolution } = useValues(toolbarConfigLogic)
    const floatingContainer = useFloatingContainer()

    if (!visible || !floatingContainer) {
        return null
    }

    // A `window_origin` host is the page the toolbar runs on, not a configured PostHog
    // app URL. Naming it sends the user to fix the wrong host, so stay generic instead.
    const knownUiHost = uiHostResolution.source === 'window_origin' ? null : uiHostResolution.host
    const apiHostSnippetValue =
        apiHostResolution.source === 'posthog_api_host' ? apiHostResolution.host : '<your_api_host>'

    return createPortal(
        <div
            className="UiHostConfigModal"
            onClick={onClose}
            onMouseDown={(e) => e.stopPropagation()}
            onTouchStart={(e) => e.stopPropagation()}
        >
            <div className="UiHostConfigModal__content" onClick={(e) => e.stopPropagation()}>
                <button className="UiHostConfigModal__close" onClick={onClose} aria-label="Close">
                    <IconX />
                </button>
                <div className="UiHostConfigModal__branding">
                    <Logomark variant="mono" />
                </div>
                <div className="UiHostConfigModal__header">
                    <strong>PostHog could not be reached</strong>
                </div>
                <p>
                    {knownUiHost ? (
                        <>
                            The toolbar tried to connect to the PostHog app at <code>{knownUiHost}</code> but could not
                            reach it.
                        </>
                    ) : (
                        <>The toolbar could not find the URL of the PostHog app, so it could not connect.</>
                    )}{' '}
                    This happens when you use a reverse proxy for <code>api_host</code>. The toolbar needs to know the
                    direct URL of the PostHog app to authenticate.
                </p>
                <p>
                    Add <code>ui_host</code> to your PostHog JS initialisation to point directly to PostHog:
                </p>
                <pre className="UiHostConfigModal__code">
                    {`posthog.init('<ph_project_api_key>', {
    api_host: '${apiHostSnippetValue}', // your reverse proxy
    ui_host: '<ph_app_host>',  // see note below
})`}
                </pre>
                <p className="UiHostConfigModal__hint">
                    Replace <code>{'<ph_app_host>'}</code> with the PostHog app URL for your region:{' '}
                    <code>https://us.posthog.com</code> (US) or <code>https://eu.posthog.com</code> (EU).
                </p>
            </div>
        </div>,
        floatingContainer
    )
}
