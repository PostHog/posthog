import './HandsFreeSurface.scss'

import { useActions, useValues } from 'kea'

import { IconMicrophone } from '@posthog/icons'

import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useShortcut } from 'lib/components/Shortcuts/useShortcut'
import { cn } from 'lib/utils/css-classes'

import { HandsFreeStatus, handsFreeLogic } from '../handsFreeLogic'

interface HandsFreeSurfaceProps {
    panelId?: string
}

const STATUS_LABEL: Record<HandsFreeStatus, string> = {
    off: '',
    starting: 'Connecting',
    listening: 'Listening',
    thinking: 'Thinking',
    speaking: 'Speaking',
}

// Emoji per visual state. Reconnecting + error deliberately render no emoji so
// the label sits alone and stays perfectly centered under the mic.
const STATUS_EMOJI: Record<HandsFreeStatus | 'reconnecting' | 'error', string> = {
    off: '',
    starting: '🎤',
    listening: '🎤',
    thinking: '🧠',
    speaking: '🔊',
    reconnecting: '',
    error: '',
}

const STATUS_HINT: Record<HandsFreeStatus, string> = {
    off: '',
    starting: 'One moment, getting microphone ready',
    listening: 'I will send your question when you pause speaking',
    thinking: 'Working on your answer',
    speaking: 'Start talking to interrupt',
}

function HandsFreeTopline({
    panelId,
    status,
    isReconnecting,
}: {
    panelId?: string
    status: HandsFreeStatus
    isReconnecting: boolean
}): JSX.Element {
    const { partialTranscript, error } = useValues(handsFreeLogic({ panelId }))
    const hint = isReconnecting ? 'Reconnecting your microphone' : STATUS_HINT[status]
    return (
        <div className="hands-free-surface__top">
            {partialTranscript ? (
                <p className="hands-free-surface__partial">{partialTranscript}</p>
            ) : (
                <p className="hands-free-surface__hint">{hint}</p>
            )}
            {error && <p className="hands-free-surface__error">{error}</p>}
        </div>
    )
}

export function HandsFreeSurface({ panelId }: HandsFreeSurfaceProps): JSX.Element | null {
    const { status, connection, error } = useValues(handsFreeLogic({ panelId }))
    const { toggleHandsFree } = useActions(handsFreeLogic({ panelId }))

    // Register the v-then-m exit shortcut while the surface is mounted.
    // HandsFreeButton owns the same shortcut for the "enter" path; same-name
    // re-registration in shortcutLogic handles the handover cleanly.
    useShortcut({
        name: 'maxHandsFree',
        keybind: [keyBinds.maxHandsFree],
        intent: 'Exit hands-free',
        interaction: 'function',
        callback: toggleHandsFree,
    })

    if (status === 'off') {
        return null
    }

    const isListening = status === 'listening'
    const isReconnecting = connection === 'reconnecting'
    const hasError = !!error

    // Reconnecting / error visuals take precedence over the listening pulse so the user
    // isn't shown a green "listening" mic when the underlying connection is dead.
    const visualState: HandsFreeStatus | 'reconnecting' | 'error' = hasError
        ? 'error'
        : isReconnecting
          ? 'reconnecting'
          : status
    const label = hasError ? 'Error' : isReconnecting ? 'Reconnecting' : STATUS_LABEL[status]
    const shouldPulse = isListening && !isReconnecting && !hasError

    return (
        <div
            className="hands-free-surface"
            data-attr="max-hands-free-surface"
            data-status={status}
            data-connection={connection}
        >
            <HandsFreeTopline panelId={panelId} status={status} isReconnecting={isReconnecting} />

            <button
                type="button"
                onClick={toggleHandsFree}
                aria-label="Exit hands-free"
                data-attr="max-hands-free-exit"
                className={cn('hands-free-surface__mic', `hands-free-surface__mic--${visualState}`, {
                    'hands-free-surface__mic--pulsing': shouldPulse,
                })}
            >
                <IconMicrophone />
            </button>

            <div className="hands-free-surface__bottom">
                {STATUS_EMOJI[visualState] && (
                    <span
                        className={cn('hands-free-surface__emoji', {
                            'hands-free-surface__emoji--pulsing': shouldPulse,
                        })}
                        aria-hidden
                    >
                        {STATUS_EMOJI[visualState]}
                    </span>
                )}
                <span className="hands-free-surface__label">{label}</span>
            </div>
        </div>
    )
}
