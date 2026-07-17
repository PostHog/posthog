import Vapi from '@vapi-ai/web'
import { memo, type RefObject, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import * as roboHogPng from '@posthog/brand/hoggies/png/robo-hog'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { Logo } from 'lib/brand'
import { pngHoggie } from 'lib/brand/hoggies'
import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { uuid } from 'lib/utils/dom'
import { fromParams } from 'lib/utils/url'

import { InterviewExportPayload } from '../types'

const HedgehogRoboHog = pngHoggie(roboHogPng)

// Fields a shared-link respondent sends to /start_call/. Empty {} for personalised links.
interface StartCallBody {
    name?: string
    respondent_key?: string
    distinct_id?: string
    session_id?: string
    _hp?: string
}

// Stable per-browser id for a shared-link respondent, scoped per share token so two topics in the
// same browser stay distinct. Persisting it means a refresh mid-call re-attaches to the same
// respondent instead of creating a duplicate. Best-effort: falls back to an in-memory id if
// localStorage is unavailable (private mode, blocked storage).
function getOrCreateRespondentKey(accessToken: string): string {
    const storageKey = `ph-interview-respondent:${accessToken}`
    try {
        const existing = window.localStorage.getItem(storageKey)
        if (existing) {
            return existing
        }
        const created = uuid()
        window.localStorage.setItem(storageKey, created)
        return created
    } catch {
        return uuid()
    }
}

// Best-effort person/session linkage: whoever built the shared link can append ?distinct_id=…&session_id=…
// so responses can be tied back to the person/session that triggered the interview. Untrusted.
function readLinkageFromUrl(): { distinct_id: string; session_id: string } {
    try {
        const params = fromParams()
        return { distinct_id: params.distinct_id ?? '', session_id: params.session_id ?? '' }
    } catch {
        return { distinct_id: '', session_id: '' }
    }
}

// Vapi surfaces several normal-completion signals through its `error` channel because
// the underlying Daily.co transport reports the local participant being evicted as
// an error. Treat these as expected end-of-call events rather than failures.
const BENIGN_END_OF_CALL_MESSAGES = ['Meeting has ended', 'Meeting ended due to ejection', 'Worker has ended call']

const isBenignEndOfCallError = (message: string): boolean =>
    BENIGN_END_OF_CALL_MESSAGES.some((pattern) => message.includes(pattern))

// Floor for the celebratory end-of-call effect. A 20-second bail-out doesn't
// deserve confetti — it reads as desperate rather than thankful. Two minutes
// is the rough point where the interviewee has given enough of a substantive
// answer that we genuinely want to thank them for the time.
const HOGFETTI_MIN_CALL_DURATION_MS = 2 * 60 * 1000

type CallState = 'already-replied' | 'idle' | 'loading' | 'connecting' | 'in-call' | 'ended' | 'error'

type ConversationPhase = 'agent-talking' | 'listening' | 'thinking'

const PHASE_LABELS: Record<ConversationPhase, string> = {
    'agent-talking': '🎤 Talking',
    listening: '👂 Listening',
    thinking: '🧠 Thinking',
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
                <HedgehogRoboHog className="w-full h-full" />
            </div>
            {state === 'in-call' && <p className="text-sm text-muted text-center mt-2">{PHASE_LABELS[phase]}</p>}
        </div>
    )
})

function PreCallIntro({
    interview,
    name,
    onNameChange,
    honeypotRef,
}: {
    interview: InterviewExportPayload
    name: string
    onNameChange: (value: string) => void
    honeypotRef: RefObject<HTMLInputElement>
}): JSX.Element {
    return (
        <>
            <h1 className="text-3xl font-bold mb-4">{interview.shared ? 'Hi there!' : `Hi ${interview.user_name}!`}</h1>
            <p className="text-lg mb-4">
                We're researching <strong>{interview.topic}</strong> and would love to hear your perspective.
            </p>
            <p className="text-muted mb-6">
                This is a 5–10 minute voice conversation with an AI interviewer. Talk like you would to a researcher on
                our team — your feedback helps us build a better product.
            </p>
            {interview.shared && (
                <div className="mb-6">
                    <label htmlFor="interview-respondent-name" className="block font-semibold mb-1">
                        What's your name?
                    </label>
                    <LemonInput
                        id="interview-respondent-name"
                        value={name}
                        onChange={onNameChange}
                        placeholder="Your name"
                        maxLength={200}
                        autoFocus
                    />
                    {/* Honeypot: hidden from real users, tempting to naive bots. Sent as `_hp`; a
                        filled value gets the request rejected server-side. */}
                    <input
                        ref={honeypotRef}
                        type="text"
                        name="company_website"
                        tabIndex={-1}
                        autoComplete="off"
                        aria-hidden="true"
                        className="hidden"
                    />
                </div>
            )}
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

function AlreadyRepliedPanel({ interview }: { interview: InterviewExportPayload }): JSX.Element {
    return (
        <>
            <h2 className="text-2xl font-bold mb-2">Thanks for your response!</h2>
            <p className="text-muted">
                We've already received your interview about <strong>{interview.topic}</strong>. We really appreciate you
                taking the time — your feedback helps us build a better product.
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
    canStart,
    onStart,
    onStop,
    onRetry,
}: {
    state: CallState
    canStart: boolean
    onStart: () => void
    onStop: () => void
    onRetry: () => void
}): JSX.Element | null {
    switch (state) {
        case 'idle':
            return (
                <LemonButton
                    type="primary"
                    size="large"
                    fullWidth
                    onClick={onStart}
                    disabledReason={canStart ? undefined : 'Enter your name to start'}
                >
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
        case 'already-replied':
        case 'connecting':
        case 'ended':
            return null
    }
}

const CallBodyPanel = memo(function CallBodyPanel({
    state,
    interview,
    errorMessage,
    name,
    onNameChange,
    honeypotRef,
    canStart,
    onStart,
    onStop,
    onRetry,
}: {
    state: CallState
    interview: InterviewExportPayload
    errorMessage: string | null
    name: string
    onNameChange: (value: string) => void
    honeypotRef: RefObject<HTMLInputElement>
    canStart: boolean
    onStart: () => void
    onStop: () => void
    onRetry: () => void
}): JSX.Element {
    const isPreCall = state === 'idle' || state === 'loading'
    return (
        <div className="flex-1 min-w-0">
            {state === 'already-replied' && <AlreadyRepliedPanel interview={interview} />}
            {isPreCall && (
                <PreCallIntro interview={interview} name={name} onNameChange={onNameChange} honeypotRef={honeypotRef} />
            )}
            {state === 'connecting' && <ConnectingPanel />}
            {state === 'in-call' && <LivePanel />}
            {state === 'ended' && <EndedPanel />}
            {state === 'error' && <ErrorPanel errorMessage={errorMessage} />}
            <div className="mt-4">
                <CallActionButton
                    state={state}
                    canStart={canStart}
                    onStart={onStart}
                    onStop={onStop}
                    onRetry={onRetry}
                />
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
async function fetchStartCallPayload(accessToken: string, body: StartCallBody): Promise<StartCallPayload> {
    const response = await fetch(`/api/user_interviews/share/${accessToken}/start_call/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
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
    const [state, setState] = useState<CallState>(interview.already_replied ? 'already-replied' : 'idle')
    // Default to 'thinking' — between connection-up and the agent's first speech-start
    // the assistant is loading its opener, which can take a few seconds. After
    // speech-end transitions us into 'listening', subsequent silent moments correctly
    // read as listening (mic is open), and only the post-user-final gap re-enters thinking.
    const [conversationPhase, setConversationPhase] = useState<ConversationPhase>('thinking')
    const [errorMessage, setErrorMessage] = useState<string | null>(null)
    // Shared links ask each respondent for their name before starting; personalised links already
    // know it. `canStart` gates the button so shared respondents can't start nameless.
    const [respondentName, setRespondentName] = useState<string>('')
    const honeypotRef = useRef<HTMLInputElement>(null)
    const canStart = !interview.shared || respondentName.trim().length > 0
    const vapiRef = useRef<Vapi | null>(null)
    const agentTalkingRef = useRef<boolean>(false)
    const lastPhaseRef = useRef<ConversationPhase>('thinking')
    const isMountedRef = useRef<boolean>(true)
    const callStartedAtRef = useRef<number | null>(null)
    const hogfettiFiredRef = useRef<boolean>(false)
    const { trigger: triggerHogfetti, HogfettiComponent } = useHogfetti({ count: 75, duration: 3000 })

    // Reused across a refresh so an interrupted call re-attaches to the same respondent instead of
    // spawning a duplicate. Only meaningful for shared links.
    const respondentKey = useMemo(
        () => (interview.shared && accessToken ? getOrCreateRespondentKey(accessToken) : ''),
        [interview.shared, accessToken]
    )

    useEffect(() => {
        document.title = `Interview · ${interview.topic}`
    }, [interview.topic])

    // Warn before an accidental refresh/close ends a live call — Vapi's browser call can't be
    // resumed across a page load, so a lost call means starting over.
    useEffect(() => {
        if (state !== 'in-call') {
            return
        }
        const onBeforeUnload = (event: BeforeUnloadEvent): void => {
            event.preventDefault()
            event.returnValue = ''
        }
        window.addEventListener('beforeunload', onBeforeUnload)
        return () => window.removeEventListener('beforeunload', onBeforeUnload)
    }, [state])

    useEffect(() => {
        if (state !== 'ended' || hogfettiFiredRef.current) {
            return
        }
        const startedAt = callStartedAtRef.current
        if (startedAt === null) {
            return
        }
        if (Date.now() - startedAt < HOGFETTI_MIN_CALL_DURATION_MS) {
            return
        }
        // Mark as fired before the early returns below so a resize-driven
        // re-run cannot retrigger the celebration. `useHogfetti`'s `trigger`
        // identity changes whenever `dimensions` updates (window resize),
        // and that dep change re-runs this effect while `state === 'ended'`.
        hogfettiFiredRef.current = true
        if (typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
            return
        }
        triggerHogfetti()
    }, [state, triggerHogfetti])

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
        lastPhaseRef.current = 'thinking'
        callStartedAtRef.current = null
        hogfettiFiredRef.current = false
        setConversationPhase('thinking')
        setState('loading')
        const body: StartCallBody = {}
        if (interview.shared) {
            const { distinct_id, session_id } = readLinkageFromUrl()
            body.name = respondentName.trim()
            body.respondent_key = respondentKey
            body.distinct_id = distinct_id
            body.session_id = session_id
            body._hp = honeypotRef.current?.value ?? ''
        }
        void (async () => {
            try {
                const startPayload = await fetchStartCallPayload(accessToken, body)
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
                // Daily.co's normal end-of-call eviction surfaces as an `error` event in the
                // Vapi SDK ("Meeting ended due to ejection: Meeting has ended"), often racing
                // with the `call-end` event. Suppress that race so the error panel doesn't
                // flash as the interview wraps up — but ONLY when the call actually got off
                // the ground. A pre-connection failure that happens to mention "Meeting has
                // ended" (e.g. joining an already-ended room) must still surface as an
                // error so the user gets the retry affordance.
                const callEndedRef = { current: false }
                const callConnectedRef = { current: false }
                vapi.on('call-end', () => {
                    callEndedRef.current = true
                    setState('ended')
                })
                vapi.on('error', (e: unknown) => {
                    const message = e instanceof Error ? e.message : ''
                    // call-end already fired — definitely post-end, swallow.
                    if (callEndedRef.current) {
                        return
                    }
                    // Benign message + we'd reached in-call → call is ending, swallow.
                    // Benign message but never connected → real failure, surface it.
                    if (callConnectedRef.current && isBenignEndOfCallError(message)) {
                        return
                    }
                    vapi.stop()
                    setErrorMessage(message || 'Vapi reported an error during the call.')
                    setState('error')
                })
                vapi.on('speech-start', () => {
                    agentTalkingRef.current = true
                    setPhase('agent-talking')
                })
                vapi.on('speech-end', () => {
                    agentTalkingRef.current = false
                    setPhase('listening')
                })
                vapi.on('message', (message: VapiTranscriptMessage) => {
                    if (message.type === 'user-interrupted') {
                        agentTalkingRef.current = false
                        setPhase('listening')
                        return
                    }
                    if (message.type !== 'transcript' || message.role !== 'user') {
                        return
                    }
                    if (agentTalkingRef.current) {
                        return
                    }
                    if (message.transcriptType === 'partial') {
                        setPhase('listening')
                    } else if (message.transcriptType === 'final') {
                        setPhase('thinking')
                    }
                })
                setState('connecting')
                await vapi.start(startPayload.assistant_id, startPayload.assistant_overrides)
                if (!isMountedRef.current) {
                    vapi.stop()
                    return
                }
                // Mark that the call actually connected — gates the benign-error suppression
                // so pre-connection "Meeting has ended" failures still surface to the user.
                callConnectedRef.current = true
                callStartedAtRef.current = Date.now()
                setState((current) => (current === 'connecting' ? 'in-call' : current))
            } catch (e) {
                if (!isMountedRef.current) {
                    return
                }
                setErrorMessage(e instanceof Error ? e.message : 'Failed to start interview.')
                setState('error')
            }
        })()
    }, [accessToken, interview.shared, respondentName, respondentKey])

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
            <HogfettiComponent />
            <div className="mb-8">
                <Logo size="md" />
            </div>

            <div className="flex flex-col md:flex-row md:items-start gap-6 md:gap-8 mb-8">
                <CallStatusPanel state={state} phase={conversationPhase} />
                <CallBodyPanel
                    state={state}
                    interview={interview}
                    errorMessage={errorMessage}
                    name={respondentName}
                    onNameChange={setRespondentName}
                    honeypotRef={honeypotRef}
                    canStart={canStart}
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
