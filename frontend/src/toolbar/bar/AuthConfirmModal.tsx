import { useActions, useValues } from 'kea'
import { createPortal } from 'react-dom'

import { IconWarning, IconX } from '@posthog/icons'

import { Logomark } from 'lib/brand/Logomark'
import { useFloatingContainer } from 'lib/hooks/useFloatingContainerContext'

import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

interface AuthConfirmModalProps {
    visible: boolean
    onClose: () => void
}

export function AuthConfirmModal({ visible, onClose }: AuthConfirmModalProps): JSX.Element | null {
    const { uiHost } = useValues(toolbarConfigLogic)
    const { confirmAuthenticate } = useActions(toolbarConfigLogic)
    const floatingContainer = useFloatingContainer()

    if (!visible || !floatingContainer) {
        return null
    }

    let hostname: string
    try {
        hostname = new URL(uiHost).hostname
    } catch {
        hostname = uiHost
    }

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
                    <Logomark />
                </div>
                <div className="UiHostConfigModal__header">
                    <strong>Confirm authentication</strong>
                </div>
                <p>
                    You will be redirected to <strong>{hostname}</strong> to sign in:
                </p>
                <pre className="UiHostConfigModal__code">{uiHost}</pre>
                <p className="flex items-center gap-1">
                    <IconWarning className="text-warning shrink-0" />
                    <span>
                        If this is not your PostHog instance, click <strong>Cancel</strong>.
                    </span>
                </p>
                <div className="flex gap-2 mt-2 justify-end">
                    <button
                        className="UiHostConfigModal__button UiHostConfigModal__button--secondary"
                        onClick={onClose}
                    >
                        Cancel
                    </button>
                    <button
                        className="UiHostConfigModal__button UiHostConfigModal__button--primary"
                        onClick={() => {
                            onClose()
                            confirmAuthenticate()
                        }}
                    >
                        Continue
                    </button>
                </div>
            </div>
        </div>,
        floatingContainer
    )
}
