import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

import { IconWarning, IconX } from '@posthog/icons'

import { Logomark } from 'lib/brand/Logomark'
import { useFloatingContainer } from 'lib/hooks/useFloatingContainerContext'

import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { toolbarLogger } from '~/toolbar/toolbarLogger'

interface AuthConfirmModalProps {
    visible: boolean
    onClose: () => void
}

const HEADING_ID = 'toolbar-auth-confirm-heading'
const DESCRIPTION_ID = 'toolbar-auth-confirm-description'

export function AuthConfirmModal({ visible, onClose }: AuthConfirmModalProps): JSX.Element | null {
    const { uiHost, authStatus } = useValues(toolbarConfigLogic)
    const { confirmAuthenticate } = useActions(toolbarConfigLogic)
    const floatingContainer = useFloatingContainer()
    const cancelRef = useRef<HTMLButtonElement | null>(null)
    const contentRef = useRef<HTMLDivElement | null>(null)

    // Focus Cancel on open: safer default for a gating confirmation.
    useEffect(() => {
        if (visible) {
            cancelRef.current?.focus()
        }
    }, [visible])

    // ESC-to-close + lightweight focus trap so keyboard users don't tab back
    // onto the host page underneath while the gate is up.
    useEffect(() => {
        if (!visible) {
            return
        }
        const handleKeyDown = (e: KeyboardEvent): void => {
            if (e.key === 'Escape') {
                e.preventDefault()
                e.stopPropagation()
                onClose()
                return
            }
            if (e.key !== 'Tab') {
                return
            }
            const content = contentRef.current
            if (!content) {
                return
            }
            const focusable = content.querySelectorAll<HTMLElement>(
                'button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
            )
            if (focusable.length === 0) {
                return
            }
            const first = focusable[0]
            const last = focusable[focusable.length - 1]
            const active = document.activeElement as HTMLElement | null
            if (e.shiftKey && active === first) {
                e.preventDefault()
                last.focus()
            } else if (!e.shiftKey && active === last) {
                e.preventDefault()
                first.focus()
            }
        }
        window.addEventListener('keydown', handleKeyDown, true)
        return () => window.removeEventListener('keydown', handleKeyDown, true)
    }, [visible, onClose])

    if (!visible) {
        return null
    }

    if (!floatingContainer) {
        // Visibility reducer flipped to true but the portal target is missing.
        // Capture so silent-fail states surface in telemetry instead of leaving
        // the user clicking Authenticate and seeing nothing.
        toolbarLogger.warn('auth', 'AuthConfirmModal visible but floatingContainer is null — skipping render')
        return null
    }

    // Parse once and derive both the prominent hostname and the sanitized origin
    // used in the code block. If parsing fails (should not happen because the
    // uiHost selector canonicalizes via `new URL().origin`), refuse to render
    // the modal rather than display attacker-controlled raw text.
    let hostname: string
    let displayUrl: string
    try {
        const parsed = new URL(uiHost)
        hostname = parsed.hostname
        displayUrl = parsed.origin
    } catch {
        toolbarLogger.warn('auth', 'AuthConfirmModal could not parse uiHost — refusing to render', { uiHost })
        return null
    }

    const isRedirecting = authStatus === 'authenticating'

    return createPortal(
        <div
            className="UiHostConfigModal"
            role="presentation"
            onMouseDown={(e) => e.stopPropagation()}
            onTouchStart={(e) => e.stopPropagation()}
        >
            <div
                ref={contentRef}
                className="UiHostConfigModal__content"
                role="dialog"
                aria-modal="true"
                aria-labelledby={HEADING_ID}
                aria-describedby={DESCRIPTION_ID}
                onClick={(e) => e.stopPropagation()}
            >
                <button
                    className="UiHostConfigModal__close"
                    onClick={onClose}
                    aria-label="Close"
                    disabled={isRedirecting}
                >
                    <IconX />
                </button>
                <div className="UiHostConfigModal__branding">
                    <Logomark />
                </div>
                <h2 id={HEADING_ID} className="UiHostConfigModal__header">
                    Confirm sign in
                </h2>
                <p id={DESCRIPTION_ID}>
                    You'll be redirected to sign in at <strong>{hostname}</strong>:
                </p>
                <pre className="UiHostConfigModal__code">{displayUrl}</pre>
                <p className="flex items-center gap-1">
                    <IconWarning className="text-warning shrink-0" />
                    <span>
                        Only continue if you recognize this domain as your PostHog instance — signing in elsewhere could
                        expose your account.
                    </span>
                </p>
                <div className="flex gap-2 mt-2 justify-end">
                    <button
                        ref={cancelRef}
                        className="UiHostConfigModal__button UiHostConfigModal__button--secondary"
                        onClick={onClose}
                        disabled={isRedirecting}
                    >
                        Cancel
                    </button>
                    <button
                        className="UiHostConfigModal__button UiHostConfigModal__button--primary"
                        onClick={() => {
                            // Don't close the modal yet — keep it visible so the user sees the
                            // redirecting state rather than the host page flickering.
                            confirmAuthenticate()
                        }}
                        disabled={isRedirecting}
                        aria-busy={isRedirecting}
                    >
                        {isRedirecting ? 'Signing in…' : 'Sign in'}
                    </button>
                </div>
            </div>
        </div>,
        floatingContainer
    )
}
