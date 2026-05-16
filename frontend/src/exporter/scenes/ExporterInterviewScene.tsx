import Vapi from '@vapi-ai/web'
import { useEffect, useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { Logo } from 'lib/brand/Logo'
import { RobotHog } from 'lib/components/hedgehogs'

import { InterviewExportPayload } from '../types'

type CallState = 'idle' | 'loading' | 'connecting' | 'in-call' | 'ended' | 'error'

interface StartCallPayload {
    public_key: string
    assistant_id: string
    assistant_overrides: {
        variableValues?: Record<string, string>
        metadata?: Record<string, string>
    }
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
    const [errorMessage, setErrorMessage] = useState<string | null>(null)
    const vapiRef = useRef<Vapi | null>(null)

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

    return (
        <div className="max-w-2xl mx-auto px-4 py-12">
            <div className="mb-8 flex items-center justify-between">
                <Logo className="text-lg" />
                <span className="text-xs text-muted">Powered by PostHog</span>
            </div>

            <div className="flex justify-center mb-6">
                <RobotHog className="w-40 h-40" alt="" />
            </div>

            <h1 className="text-3xl font-bold mb-4">Hi {interview.user_name}!</h1>

            <p className="text-lg mb-4">
                We're researching <strong>{interview.topic}</strong> and would love to hear your perspective.
            </p>

            <p className="text-muted mb-6">
                This is a 5–10 minute voice conversation with an AI interviewer. Talk like you would to a researcher on
                our team — your feedback helps us build a better product.
            </p>

            <div className="bg-accent-highlight border border-accent p-4 rounded mb-8 text-sm">
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

            {state === 'idle' && (
                <LemonButton type="primary" size="large" fullWidth onClick={start}>
                    Start interview
                </LemonButton>
            )}
            {state === 'loading' && <p>Loading interviewer…</p>}
            {state === 'connecting' && <p>Connecting…</p>}
            {state === 'in-call' && (
                <div>
                    <p className="mb-4">You're live with the interviewer.</p>
                    <LemonButton type="secondary" onClick={stop}>
                        End interview
                    </LemonButton>
                </div>
            )}
            {state === 'ended' && (
                <p className="text-success">
                    Thanks for taking the time! Your conversation has been recorded — we'll be in touch.
                </p>
            )}
            {state === 'error' && (
                <div className="text-danger">
                    <p className="mb-2">{errorMessage ?? 'Something went wrong.'}</p>
                    <LemonButton type="secondary" onClick={() => setState('idle')}>
                        Try again
                    </LemonButton>
                </div>
            )}

            <p className="text-xs text-muted text-center mt-12">
                Your conversation will be transcribed and analyzed to help improve PostHog. We won't share your
                individual responses publicly.
            </p>
        </div>
    )
}
