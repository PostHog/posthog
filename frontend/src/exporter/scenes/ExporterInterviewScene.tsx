import Vapi from '@vapi-ai/web'
import { memo, useCallback, useEffect, useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { Logo } from 'lib/brand/Logo'
import { RobotHog } from 'lib/components/hedgehogs'

import { InterviewExportPayload } from '../types'

type CallState = 'idle' | 'loading' | 'connecting' | 'in-call' | 'ended' | 'error'

type ConversationPhase = 'agent-talking' | 'user-speaking' | 'waiting'

const PHASE_LABELS: Record<ConversationPhase, string> = {
    'agent-talking': '🎤 Talking',
    'user-speaking': '👂 Listening',
    waiting: '🧠 Thinking',
}

interface VapiTranscriptMessage {
    type?: string
    role?: string
    transcriptType?: string
}

interface StartCallPayload {
    public_key: string
    assistant_id: string
    assistant_overrides: {
        firstMessage?: string
        variableValues?: Record<string, string>
        metadata?: Record<string, string>
    }
}

const CallStatusPanel = memo(function CallStatusPanel({
    state,
    phase,
}: {
    state: CallState
    phase: ConversationPhase
}): JSX.Element {
    return (
        <div className="flex-shrink-0 mx-auto md:mx-0 md:w-40">
            <div className="w-40 h-40 mx-auto">
                <RobotHog className="w-full h-full" alt="" />
            </div>
            {state === 'in-call' && <p className="text-sm text-muted text-center mt-2">{PHASE_LABELS[phase]}</p>}
        </div>
    )
})

function PreCallIntro({ interview }: { interview: InterviewExportPayload }): JSX.Element {
    return (
        <>
            <h1 className="text-3xl font-bold mb-4">Hi {interview.user_name}!</h1>
            <p className="text-lg mb-4">
                We're researching <strong>{interview.topic}</strong> and would love to hear your perspective.
            </p>
            <p className="text-muted mb-6">
                This is a 5–10 minute voice conversation with an AI interviewer. Talk like you would to a researcher on
                our team — your feedback helps us build a better product.
            </p>
            <div className="bg-accent-highlight border border-accent p-4 rounded mb-6 text-sm">
                <strong>How it works</strong>
                <ol className="list-decimal pl-5 mt-2 space-y-1">
                    <li>
                        Click <em>Start interview</em> below.
                    </li>
                    <li>Allow microphone access when prompted.</li>
                    <li>Have a casual conversation — the AI will guide you through a few questions.</li>
                    <li>You can end the call any time.</li>
                </ol>
            </div>
        </>
    )
}

function ConnectingPanel(): JSX.Element {
    return (
        <>
            <h2 className="text-2xl font-bold mb-2">Connecting…</h2>
            <p className="text-muted">Hold tight while we connect you to the AI interviewer.</p>
        </>
    )
}

function LivePanel(): JSX.Element {
    return (
        <>
            <h2 className="text-2xl font-bold mb-2">You're live</h2>
            <p className="text-muted mb-2">Talk as you would to a researcher on our team.</p>
            <p className="text-xs text-muted">
                End the call any time using the button below — the recording will still be saved.
            </p>
        </>
    )
}

function EndedPanel(): JSX.Element {
    return (
        <>
            <h2 className="text-2xl font-bold mb-2">Thanks for taking the time!</h2>
            <p className="text-muted">
                Your conversation has been recorded — we'll be in touch if we have follow-up questions.
            </p>
        </>
    )
}

function ErrorPanel({ errorMessage }: { errorMessage: string | null }): JSX.Element {
    return (
        <div className="text-danger">
            <h2 className="text-2xl font-bold mb-2">Something went wrong</h2>
            <p className="mb-2">{errorMessage ?? 'Unknown error.'}</p>
        </div>
    )
}

function CallActionButton({
    state,
    onStart,
    onStop,
    onRetry,
}: {
    state: CallState
    onStart: () => void
    onStop: () => void
    onRetry: () => void
}): JSX.Element | null {
    switch (state) {
        case 'idle':
            return (
                <LemonButton type="primary" size="large" fullWidth onClick={onStart}>
                    Start interview
                </LemonButton>
            )
        case 'loading':
            return <p>Loading interviewer…</p>
        case 'in-call':
            return (
                <LemonButton type="secondary" onClick={onStop}>
                    End interview
                </LemonButton>
            )
        case 'error':
            return (
                <LemonButton type="secondary" onClick={onRetry}>
                    Try again
                </LemonButton>
            )
        case 'connecting':
        case 'ended':
            return null
    }
}

const CallBodyPanel = memo(function CallBodyPanel({
    state,
    interview,
    errorMessage,
    onStart,
    onStop,
    onRetry,
}: {
    state: CallState
    interview: InterviewExportPayload
    errorMessage: string | null
    onStart: () => void
    onStop: () => void
    onRetry: () => void
}): JSX.Element {
    const isPreCall = state === 'idle' || state === 'loading'
    return (
        <div className="flex-1 min-w-0">
            {isPreCall && <PreCallIntro interview={interview} />}
            {state === 'connecting' && <ConnectingPanel />}
            {state === 'in-call' && <LivePanel />}
            {state === 'ended' && <EndedPanel />}
            {state === 'error' && <ErrorPanel errorMessage={errorMessage} />}
            <div className="mt-4">
                <CallActionButton state={state} onStart={onStart} onStop={onStop} onRetry={onRetry} />
            </div>
        </div>
    )
})

/**
 * Fetch the Vapi public key, assistant id, and *full* assistant overrides (including
 * `agent_context`) from the server only when the interviewee clicks Start. Keeps the
 * personalized agent context out of the initial HTML payload, so a recipient can't
 * see "this person is a heavy user, be empathetic" just by viewing source.
 */
async function fetchStartCallPayload(accessToken: string): Promise<StartCallPayload> {
    const response = await fetch(`/api/user_interviews/share/${accessToken}/start_call/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
    })
    if (!response.ok) {
        const text = await response.text()
        throw new Error(text || `Server responded ${response.status}`)
    }
    return response.json()
}

export default function ExporterInterviewScene({
    interview,
    accessToken,
}: {
    interview: InterviewExportPayload
    accessToken?: string
}): JSX.Element {
    const [state, setState] = useState<CallState>('idle')
    const [conversationPhase, setConversationPhase] = useState<ConversationPhase>('waiting')
    const [errorMessage, setErrorMessage] = useState<string | null>(null)
    const vapiRef = useRef<Vapi | null>(null)
    const agentTalkingRef = useRef<boolean>(false)
    const lastPhaseRef = useRef<ConversationPhase>('waiting')
    const isMountedRef = useRef<boolean>(true)

    useEffect(() => {
        document.title = `Interview · ${interview.topic}`
    }, [interview.topic])

    useEffect(() => {
        return () => {
            isMountedRef.current = false
            vapiRef.current?.stop()
            vapiRef.current = null
        }
    }, [])

    const start = useCallback((): void => {
        if (!accessToken) {
            setErrorMessage('Interview link is missing its access token. Open the URL you were emailed.')
            setState('error')
            return
        }
        vapiRef.current?.stop()
        vapiRef.current = null
        agentTalkingRef.current = false
        lastPhaseRef.current = 'waiting'
        setConversationPhase('waiting')
        setState('loading')
        void (async () => {
            try {
                const startPayload = await fetchStartCallPayload(accessToken)
                if (!isMountedRef.current) {
                    return
                }
                const vapi = new Vapi(startPayload.public_key)
                vapiRef.current = vapi
                const setPhase = (next: ConversationPhase): void => {
                    if (lastPhaseRef.current === next) {
                        return
                    }
                    lastPhaseRef.current = next
                    setConversationPhase(next)
                }
                vapi.on('call-end', () => setState('ended'))
                vapi.on('error', (e: unknown) => {
                    vapi.stop()
                    setErrorMessage(e instanceof Error ? e.message : 'Vapi reported an error during the call.')
                    setState('error')
                })
                vapi.on('speech-start', () => {
                    agentTalkingRef.current = true
                    setPhase('agent-talking')
                })
                vapi.on('speech-end', () => {
                    agentTalkingRef.current = false
                    setPhase('waiting')
                })
                vapi.on('message', (message: VapiTranscriptMessage) => {
                    if (message.type === 'user-interrupted') {
                        agentTalkingRef.current = false
                        setPhase('user-speaking')
                        return
                    }
                    if (message.type !== 'transcript' || message.role !== 'user') {
                        return
                    }
                    if (agentTalkingRef.current) {
                        return
                    }
                    if (message.transcriptType === 'partial') {
                        setPhase('user-speaking')
                    } else if (message.transcriptType === 'final') {
                        setPhase('waiting')
                    }
                })
                setState('connecting')
                await vapi.start(startPayload.assistant_id, startPayload.assistant_overrides)
                if (!isMountedRef.current) {
                    vapi.stop()
                    return
                }
                setState((current) => (current === 'connecting' ? 'in-call' : current))
            } catch (e) {
                if (!isMountedRef.current) {
                    return
                }
                setErrorMessage(e instanceof Error ? e.message : 'Failed to start interview.')
                setState('error')
            }
        })()
    }, [accessToken])

    const stop = useCallback((): void => {
        vapiRef.current?.stop()
        setState('ended')
    }, [])

    const retry = useCallback((): void => {
        setErrorMessage(null)
        setState('idle')
    }, [])

    return (
        <div className="max-w-2xl mx-auto px-4 py-12">
            <div className="mb-8 flex items-center justify-between">
                <Logo className="text-lg" />
                <span className="text-xs text-muted">Powered by PostHog</span>
            </div>

            <div className="flex flex-col md:flex-row md:items-start gap-6 md:gap-8 mb-8">
                <CallStatusPanel state={state} phase={conversationPhase} />
                <CallBodyPanel
                    state={state}
                    interview={interview}
                    errorMessage={errorMessage}
                    onStart={start}
                    onStop={stop}
                    onRetry={retry}
                />
            </div>

            <p className="text-xs text-muted text-center mt-12">
                Your conversation will be transcribed and analyzed to help improve PostHog. We won't share your
                individual responses publicly.
            </p>
        </div>
    )
}
