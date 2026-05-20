import './HandsFreeSurface.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconMicrophone } from '@posthog/icons'

import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useAppShortcut } from 'lib/components/AppShortcuts/useAppShortcut'

import { HandsFreeStatus, handsFreeLogic } from '../handsFreeLogic'

interface HandsFreeSurfaceProps {
    tabId: string
}

const STATUS_LABEL: Record<HandsFreeStatus, string> = {
    off: '',
    starting: 'Connecting',
    listening: 'Listening',
    thinking: 'Thinking',
    speaking: 'Speaking',
}

const STATUS_HINT: Record<HandsFreeStatus, string> = {
    off: '',
    starting: 'One moment, getting microphone ready',
    listening: 'I will send your question when you pause speaking',
    thinking: 'Working on your answer',
    speaking: 'Start talking to interrupt',
}

function HandsFreeTopline({ tabId, status }: { tabId: string; status: HandsFreeStatus }): JSX.Element {
    const { partialTranscript, error } = useValues(handsFreeLogic({ tabId }))
    return (
        <div className="hands-free-surface__top">
            {partialTranscript ? (
                <p className="hands-free-surface__partial">{partialTranscript}</p>
            ) : (
                <p className="hands-free-surface__hint">{STATUS_HINT[status]}</p>
            )}
            {error && <p className="hands-free-surface__error">{error}</p>}
        </div>
    )
}

export function HandsFreeSurface({ tabId }: HandsFreeSurfaceProps): JSX.Element | null {
    const { status } = useValues(handsFreeLogic({ tabId }))
    const { toggleHandsFree, interruptSpeaking } = useActions(handsFreeLogic({ tabId }))

    // Register the v-then-m exit shortcut while the surface is mounted.
    // HandsFreeButton owns the same shortcut for the "enter" path; same-name
    // re-registration in appShortcutLogic handles the handover cleanly.
    useAppShortcut({
        name: 'maxHandsFree',
        keybind: [keyBinds.maxHandsFree],
        intent: 'Exit hands-free',
        interaction: 'function',
        callback: toggleHandsFree,
    })

    if (status === 'off') {
        return null
    }

    // Listening pulses (your turn), thinking spins a ring around the icon (working on it).
    // Both keep the mic icon visible so the user knows the button is still tap-to-exit.
    const isListening = status === 'listening'
    const isSpeaking = status === 'speaking'
    // Tapping the mic while Max is talking interrupts the TTS and returns to listening so
    // you can ask the next question. Tapping in any other state exits hands-free entirely.
    const onMicClick = isSpeaking ? interruptSpeaking : toggleHandsFree
    const ariaLabel = isSpeaking ? 'Stop speaking and listen' : 'Exit hands-free'

    return (
        <div className="hands-free-surface" data-attr="max-hands-free-surface" data-status={status}>
            <HandsFreeTopline tabId={tabId} status={status} />

            <button
                type="button"
                onClick={onMicClick}
                aria-label={ariaLabel}
                data-attr={isSpeaking ? 'max-hands-free-interrupt' : 'max-hands-free-exit'}
                className={clsx(
                    'hands-free-surface__mic',
                    `hands-free-surface__mic--${status}`,
                    isListening && 'hands-free-surface__mic--pulsing'
                )}
            >
                <IconMicrophone />
            </button>

            <div className="hands-free-surface__bottom">
                <span
                    className={clsx(
                        'hands-free-surface__dot',
                        `hands-free-surface__dot--${status}`,
                        isListening && 'hands-free-surface__dot--pulsing'
                    )}
                    aria-hidden
                />
                <span className="hands-free-surface__label">{STATUS_LABEL[status]}</span>
            </div>
        </div>
    )
}
