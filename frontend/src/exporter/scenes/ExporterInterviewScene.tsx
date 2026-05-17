import Vapi from '@vapi-ai/web'
import { useEffect, useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { Logo } from 'lib/brand/Logo'
import { HeartHog, MicrophoneHog, ProfessorHog, RobotHog } from 'lib/components/hedgehogs'

import { InterviewExportPayload } from '../types'

type CallState = 'idle' | 'loading' | 'connecting' | 'in-call' | 'ended' | 'error'

type ConversationPhase = 'agent-talking' | 'user-speaking' | 'waiting'

const USER_SPEAKING_VOLUME_THRESHOLD = 0.05

interface StartCallPayload {
    public_key: string
    assistant_id: string
    assistant_overrides: {
        firstMessage?: string
        variableValues?: Record<string, string>
        metadata?: Record<string, string>
    }
}

interface PhaseStatusProps {
    phase: ConversationPhase
}

function HogForCallState({ state, phase }: { state: CallState; phase: ConversationPhase }): JSX.Element {
    if (state === 'in-call') {
        if (phase === 'agent-talking') {
            return <RobotHog className="w-full h-full" alt="" />
        }
        if (phase === 'user-speaking') {
            return <MicrophoneHog className="w-full h-full" alt="" />
        }
        return <ProfessorHog className="w-full h-full" alt="" />
    }
    if (state === 'ended') {
        return <HeartHog className="w-full h-full" alt="" />
    }
    return <RobotHog className="w-full h-full" alt="" />
}

function PhaseCaption({ phase }: PhaseStatusProps): JSX.Element {
    const labels: Record<ConversationPhase, string> = {
        'agent-talking': 'Talking…',
        'user-speaking': 'Listening…',
        waiting: 'Thinking…',
    }
    return <p className="text-sm text-muted text-center mt-2">{labels[phase]}</p>
}

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

    useEffect(() => {
        document.title = `Interview · ${interview.topic}`
    }, [interview.topic])

    useEffect(() => {
        return () => {
            vapiRef.current?.stop()
        }
    }, [])

    const start = async (): Promise<void> => {
        if (!accessToken) {
            setErrorMessage('Interview link is missing its access token. Open the URL you were emailed.')
            setState('error')
            return
        }
        setState('loading')
        try {
            const startPayload = await fetchStartCallPayload(accessToken)
            const vapi = new Vapi(startPayload.public_key)
            vapiRef.current = vapi
            vapi.on('call-end', () => setState('ended'))
            vapi.on('error', (e: unknown) => {
                setErrorMessage(e instanceof Error ? e.message : 'Vapi reported an error during the call.')
                setState('error')
            })
            vapi.on('speech-start', () => {
                agentTalkingRef.current = true
                setConversationPhase('agent-talking')
            })
            vapi.on('speech-end', () => {
                agentTalkingRef.current = false
                setConversationPhase('waiting')
            })
            vapi.on('volume-level', (volume: number) => {
                if (agentTalkingRef.current) {
                    return
                }
                setConversationPhase(volume > USER_SPEAKING_VOLUME_THRESHOLD ? 'user-speaking' : 'waiting')
            })
            setState('connecting')
            await vapi.start(startPayload.assistant_id, startPayload.assistant_overrides)
            setState('in-call')
        } catch (e) {
            setErrorMessage(e instanceof Error ? e.message : 'Failed to start interview.')
            setState('error')
        }
    }

    const stop = (): void => {
        vapiRef.current?.stop()
        setState('ended')
    }

    const isPreCall = state === 'idle' || state === 'loading'

    return (
        <div className="max-w-2xl mx-auto px-4 py-12">
            <div className="mb-8 flex items-center justify-between">
                <Logo className="text-lg" />
                <span className="text-xs text-muted">Powered by PostHog</span>
            </div>

            <div className="flex flex-col md:flex-row md:items-start gap-6 md:gap-8 mb-8">
                <div className="flex-shrink-0 mx-auto md:mx-0 md:w-40">
                    <div className="w-40 h-40 mx-auto">
                        <HogForCallState state={state} phase={conversationPhase} />
                    </div>
                    {state === 'in-call' && <PhaseCaption phase={conversationPhase} />}
                </div>

                <div className="flex-1 min-w-0">
                    {isPreCall && (
                        <>
                            <h1 className="text-3xl font-bold mb-4">Hi {interview.user_name}!</h1>
                            <p className="text-lg mb-4">
                                We're researching <strong>{interview.topic}</strong> and would love to hear your
                                perspective.
                            </p>
                            <p className="text-muted mb-6">
                                This is a 5–10 minute voice conversation with an AI interviewer. Talk like you would to
                                a researcher on our team — your feedback helps us build a better product.
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
                    )}
                    {state === 'connecting' && (
                        <>
                            <h2 className="text-2xl font-bold mb-2">Connecting…</h2>
                            <p className="text-muted">Hold tight while we wake the interviewer up.</p>
                        </>
                    )}
                    {state === 'in-call' && (
                        <>
                            <h2 className="text-2xl font-bold mb-2">You're live</h2>
                            <p className="text-muted mb-2">Talk as you would to a researcher on our team.</p>
                            <p className="text-xs text-muted">
                                End the call any time using the button below — the recording will still be saved.
                            </p>
                        </>
                    )}
                    {state === 'ended' && (
                        <>
                            <h2 className="text-2xl font-bold mb-2">Thanks for taking the time!</h2>
                            <p className="text-muted">
                                Your conversation has been recorded — we'll be in touch if we have follow-up questions.
                            </p>
                        </>
                    )}
                    {state === 'error' && (
                        <div className="text-danger">
                            <h2 className="text-2xl font-bold mb-2">Something went wrong</h2>
                            <p className="mb-2">{errorMessage ?? 'Unknown error.'}</p>
                        </div>
                    )}

                    <div className="mt-4">
                        {state === 'idle' && (
                            <LemonButton type="primary" size="large" fullWidth onClick={start}>
                                Start interview
                            </LemonButton>
                        )}
                        {state === 'loading' && <p>Loading interviewer…</p>}
                        {state === 'in-call' && (
                            <LemonButton type="secondary" onClick={stop}>
                                End interview
                            </LemonButton>
                        )}
                        {state === 'error' && (
                            <LemonButton type="secondary" onClick={() => setState('idle')}>
                                Try again
                            </LemonButton>
                        )}
                    </div>
                </div>
            </div>

            <p className="text-xs text-muted text-center mt-12">
                Your conversation will be transcribed and analyzed to help improve PostHog. We won't share your
                individual responses publicly.
            </p>
        </div>
    )
}
