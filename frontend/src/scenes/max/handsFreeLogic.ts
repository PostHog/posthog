// Hands-free conversational mode for Max — STT via ElevenLabs Scribe (browser → WS direct),
// TTS via the browser's native speechSynthesis. Built for mobile-web use (gym, walking).
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { handsFreeLogicType } from './handsFreeLogicType'
import { AssistantSummary, buildSpokenText } from './handsFreeUtils'
import { maxLogic } from './maxLogic'
import { maxThreadLogic } from './maxThreadLogic'

export type HandsFreeStatus = 'off' | 'starting' | 'listening' | 'thinking' | 'speaking'
export type HandsFreeConnection = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'closed'

const SCRIBE_REALTIME_MODEL_ID = 'scribe_v2_realtime'

export interface HandsFreeLogicProps {
    panelId?: string // identifies the MaxLogic instance backing this panel (scene tab id or side panel)
}

interface ScribeConnection {
    close: () => void
    on: (event: string, listener: (payload: any) => void) => void
    off: (event: string, listener: (payload: any) => void) => void
}

interface ScribeNamespace {
    connect: (options: {
        token: string
        modelId: string
        commitStrategy?: string
        microphone?: { echoCancellation?: boolean; noiseSuppression?: boolean }
    }) => ScribeConnection
}

type RealtimeEventsEnum = Record<string, string>
type CommitStrategyEnum = { MANUAL: string; VAD: string }

let cachedSdkPromise: Promise<{
    Scribe: ScribeNamespace
    RealtimeEvents: RealtimeEventsEnum
    CommitStrategy: CommitStrategyEnum
}> | null = null

async function loadScribeSdk(): Promise<{
    Scribe: ScribeNamespace
    RealtimeEvents: RealtimeEventsEnum
    CommitStrategy: CommitStrategyEnum
}> {
    if (!cachedSdkPromise) {
        cachedSdkPromise = import(/* webpackChunkName: "elevenlabs-client" */ '@elevenlabs/client')
            .then((mod) => ({
                Scribe: (mod as unknown as { Scribe: ScribeNamespace }).Scribe,
                RealtimeEvents: (mod as unknown as { RealtimeEvents: RealtimeEventsEnum }).RealtimeEvents,
                CommitStrategy: (mod as unknown as { CommitStrategy: CommitStrategyEnum }).CommitStrategy,
            }))
            .catch((err) => {
                cachedSdkPromise = null
                throw err
            })
    }
    return cachedSdkPromise
}

export const handsFreeLogic = kea<handsFreeLogicType>([
    props({} as HandsFreeLogicProps),
    key((props) => props.panelId as string),
    path((key) => ['scenes', 'max', 'handsFreeLogic', key]),

    connect(({ panelId }: HandsFreeLogicProps) => ({
        values: [maxLogic({ panelId }), ['threadLogicKey']],
    })),

    actions({
        enterHandsFree: true,
        exitHandsFree: (reason?: string) => ({ reason: reason ?? 'user' }),
        toggleHandsFree: true,
        setStatus: (status: HandsFreeStatus) => ({ status }),
        setConnection: (connection: HandsFreeConnection) => ({ connection }),
        setError: (error: string | null) => ({ error }),
        setPartialTranscript: (text: string) => ({ text }),
        commitTranscript: (text: string) => ({ text }),
        speakAssistantResponse: (summary: AssistantSummary) => ({ summary }),
        cancelSpeaking: true,
        // Stop TTS playback and go back to listening — fired only when Scribe transcribes
        // genuine user speech over Max's TTS (voice barge-in). The mic button no longer
        // tap-interrupts; tapping it always exits hands-free entirely.
        interruptSpeaking: true,
        setSdkAvailable: (available: boolean) => ({ available }),
    }),

    reducers({
        status: [
            'off' as HandsFreeStatus,
            {
                setStatus: (_, { status }) => status,
            },
        ],
        connection: [
            'idle' as HandsFreeConnection,
            {
                setConnection: (_, { connection }) => connection,
                exitHandsFree: () => 'idle' as HandsFreeConnection,
            },
        ],
        error: [
            null as string | null,
            {
                setError: (_, { error }) => error,
                enterHandsFree: () => null,
                exitHandsFree: () => null,
            },
        ],
        partialTranscript: [
            '' as string,
            {
                setPartialTranscript: (_, { text }) => text,
                commitTranscript: () => '',
                exitHandsFree: () => '',
            },
        ],
        // null = probe not yet finished, true = Scribe present, false = SDK missing or load failed
        sdkAvailable: [
            null as boolean | null,
            {
                setSdkAvailable: (_, { available }) => available,
            },
        ],
    }),

    selectors({
        isActive: [(s) => [s.status], (status) => status !== 'off'],
        // Render the mic button when the probe hasn't completed yet (null) or has succeeded (true).
        // Hide it only once we've confirmed the SDK can't be used.
        canUseHandsFree: [(s) => [s.sdkAvailable], (sdkAvailable) => sdkAvailable !== false],
    }),

    listeners(({ actions, values, cache, props }) => ({
        toggleHandsFree: () => {
            if (values.status === 'off') {
                actions.enterHandsFree()
            } else {
                actions.exitHandsFree()
            }
        },

        enterHandsFree: async () => {
            if (values.status !== 'off') {
                return
            }
            actions.setStatus('starting')
            actions.setConnection('connecting')

            // Per-session analytics counters, captured at exit so a single PostHog query can
            // build session-length and turn-count distributions without re-aggregating events.
            cache.sessionStartedAt = Date.now()
            cache.userTurnCount = 0
            cache.assistantTurnCount = 0
            cache.interruptedCount = 0

            // iOS Safari requires the first audio playback (HTMLAudioElement.play()) to be
            // initiated from a user-gesture handler. The mic-button click IS that gesture, so
            // we prime a silent Audio element here. Subsequent .play() calls (driven by Max
            // responses arriving over the network) then succeed without re-prompting.
            try {
                const primer = new Audio()
                primer.muted = true
                primer.src =
                    'data:audio/mpeg;base64,SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4LjI5LjEwMAAAAAAAAAAAAAAA//tQxAADB8AhSmxhhgAAAAAAAAAAAExBTUUzLjEwMACqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//tSxAADB8AhSmxhhgAAAAAAAAAAAExBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq'
                void primer.play().catch(() => undefined)
            } catch {
                // best-effort
            }

            let sdk
            try {
                sdk = await loadScribeSdk()
            } catch (err) {
                posthog.captureException(err)
                actions.setError('Could not load the hands-free SDK.')
                lemonToast.error('Hands-free could not load. Please try again.')
                actions.exitHandsFree('sdk_load_failed')
                return
            }
            if (values.status === 'off') {
                return
            }

            const { Scribe, RealtimeEvents, CommitStrategy } = sdk
            if (!Scribe || typeof Scribe.connect !== 'function') {
                // Should be unreachable — the mount-time probe should have already hidden the
                // button when the SDK doesn't expose Scribe. If we get here, capture so we can
                // see it in PostHog and bail without confusing the user.
                posthog.captureException(new Error('handsFree: Scribe namespace missing from @elevenlabs/client'))
                actions.setSdkAvailable(false)
                actions.exitHandsFree('sdk_missing_scribe')
                return
            }

            cache.reconnectAttempts = 0

            // Mints a fresh token, opens a Scribe connection, and wires event handlers.
            // Called for the initial session and on reconnect after an unexpected close.
            // Returns true on success, false when the caller should give up.
            const establishConnection = async (isReconnect: boolean): Promise<boolean> => {
                let token: string
                try {
                    const response = await api.maxHandsFree.token()
                    token = response.token
                } catch (err) {
                    posthog.captureException(err)
                    if (!isReconnect) {
                        actions.setError('Could not start hands-free session.')
                        lemonToast.error('Hands-free could not start. Please try again.')
                    }
                    actions.exitHandsFree(isReconnect ? 'reconnect_token_failed' : 'token_failed')
                    return false
                }
                if (values.status === 'off') {
                    return false
                }
                let connection: ScribeConnection
                try {
                    connection = Scribe.connect({
                        token,
                        modelId: SCRIBE_REALTIME_MODEL_ID,
                        // SDK defaults to MANUAL — we need VAD so silence on the mic auto-commits
                        // the speech segment and triggers askMax. Without this it isn't hands-free.
                        commitStrategy: CommitStrategy?.VAD ?? 'vad',
                        microphone: { echoCancellation: true, noiseSuppression: true },
                    })
                } catch (err) {
                    posthog.captureException(err)
                    const message = (err as Error)?.message ?? ''
                    const isPermissionError =
                        /permission|notallowed|denied/i.test(message) ||
                        (err as { name?: string })?.name === 'NotAllowedError'
                    if (isPermissionError) {
                        actions.setError('Microphone access was denied.')
                        lemonToast.error('Microphone access was denied. Hands-free disabled.')
                        actions.exitHandsFree('mic_permission_denied')
                    } else if (isReconnect) {
                        actions.exitHandsFree('reconnect_failed')
                    } else {
                        actions.setError(`Hands-free connection failed: ${message || 'unknown error'}`)
                        lemonToast.error('Hands-free failed to start. See console for details.')
                        actions.exitHandsFree('connection_failed')
                    }
                    return false
                }
                cache.connection = connection
                wireConnectionEvents(connection)
                return true
            }

            const onOpen = (): void => actions.setConnection('connected')
            const onSessionStarted = (): void => {
                const wasStarting = values.status === 'starting'
                const wasReconnecting = cache.isReconnecting === true
                cache.isReconnecting = false
                if (wasStarting || wasReconnecting) {
                    actions.setStatus('listening')
                }
                if (wasStarting) {
                    posthog.capture('max hands-free entered')
                }
                if (wasReconnecting) {
                    posthog.capture('max hands-free reconnected', {
                        attempts: cache.reconnectAttempts ?? 1,
                    })
                }
            }
            // While 'speaking', the Scribe mic stream stays open (we can't cheaply pause it)
            // and the speakers' TTS audio bleeds back into the mic — Scribe transcribes its
            // own voice. To support real barge-in (user talks over Max -> Max shuts up and
            // listens) without self-triggering, we compare incoming partials to what Max is
            // currently saying. If the partial is a substring of the spoken text, it's
            // self-transcription bleed; otherwise the user is talking over Max.
            const onPartial = (payload: any): void => {
                const text: string = payload?.text ?? payload?.transcript ?? ''
                if (values.status === 'speaking') {
                    const partialLower = normaliseForBargeInMatch(text)
                    const spokenLower: string = cache.spokenTextLower ?? ''
                    const reason = classifyPartial(spokenLower, partialLower)
                    if (reason) {
                        posthog.capture('max hands-free partial suppressed', {
                            reason,
                            partial_chars: partialLower.length,
                            spoken_chars: spokenLower.length,
                            phase: 'partial',
                        })
                        return
                    }
                    // User is talking over Max — barge in: stop TTS, flip to listening, then
                    // let the partial-transcript reducer below pick up the user's words.
                    actions.interruptSpeaking()
                }
                if (values.status === 'listening') {
                    actions.setPartialTranscript(text)
                }
            }
            const onCommitted = (payload: any): void => {
                const text: string = (payload?.text ?? payload?.transcript ?? '').trim()
                if (!text) {
                    return
                }
                if (values.status === 'speaking') {
                    const committedLower = normaliseForBargeInMatch(text)
                    const spokenLower: string = cache.spokenTextLower ?? ''
                    const reason = classifyPartial(spokenLower, committedLower)
                    if (reason) {
                        posthog.capture('max hands-free partial suppressed', {
                            reason,
                            partial_chars: committedLower.length,
                            spoken_chars: spokenLower.length,
                            phase: 'committed',
                        })
                        return
                    }
                    actions.interruptSpeaking()
                }
                if (values.status !== 'listening') {
                    return
                }
                actions.commitTranscript(text)
            }
            const onClose = (): void => {
                if (values.status === 'off') {
                    return
                }
                // Single retry-with-fresh-token on unexpected close — mobile network blips
                // (the exact gym/walking use case this targets) should not tear down the
                // session. Beyond one attempt we give up to avoid a reconnect storm.
                const attempts = (cache.reconnectAttempts ?? 0) + 1
                cache.reconnectAttempts = attempts
                if (attempts > 1) {
                    actions.setConnection('closed')
                    actions.exitHandsFree('connection_closed')
                    return
                }
                actions.setConnection('reconnecting')
                cache.isReconnecting = true
                posthog.capture('max hands-free reconnect attempted', { attempt: attempts })
                cache.connection = undefined
                void establishConnection(true)
            }
            const onError = (payload: any): void => {
                posthog.captureException(new Error(`scribe error: ${JSON.stringify(payload ?? {})}`))
                actions.setError('Hands-free connection error.')
                actions.exitHandsFree('scribe_error')
            }

            const wireConnectionEvents = (connection: ScribeConnection): void => {
                connection.on(RealtimeEvents.OPEN, onOpen)
                connection.on(RealtimeEvents.SESSION_STARTED, onSessionStarted)
                connection.on(RealtimeEvents.PARTIAL_TRANSCRIPT, onPartial)
                connection.on(RealtimeEvents.COMMITTED_TRANSCRIPT, onCommitted)
                connection.on(RealtimeEvents.CLOSE, onClose)
                connection.on(RealtimeEvents.ERROR, onError)
            }

            await establishConnection(false)
        },

        exitHandsFree: ({ reason }) => {
            posthog.capture('max hands-free exited', {
                reason,
                duration_ms: cache.sessionStartedAt ? Date.now() - cache.sessionStartedAt : null,
                user_turns: cache.userTurnCount ?? 0,
                assistant_turns: cache.assistantTurnCount ?? 0,
                interruptions: cache.interruptedCount ?? 0,
            })
            actions.cancelSpeaking()
            const connection = cache.connection as ScribeConnection | undefined
            if (connection) {
                try {
                    connection.close()
                } catch {
                    // best-effort
                }
                cache.connection = undefined
            }
            actions.setStatus('off')
        },

        commitTranscript: ({ text }) => {
            const threadKey = values.threadLogicKey
            const threadLogic = threadKey
                ? maxThreadLogic.findMounted({
                      panelId: props.panelId,
                      conversationId: threadKey,
                  })
                : null
            if (!threadLogic) {
                actions.setError('Could not find an active conversation to send the message to.')
                actions.exitHandsFree('no_thread')
                return
            }
            actions.setStatus('thinking')
            cache.userTurnCount = (cache.userTurnCount ?? 0) + 1
            posthog.capture('max hands-free user spoke', { transcript_chars: text.length })
            threadLogic.actions.askMax(text)
        },

        speakAssistantResponse: async ({ summary }) => {
            if (values.status === 'off') {
                return
            }
            // guard re-entry — if two assistant turns complete back-to-back, tear down the
            // previous playback (revokes blob URL, aborts inflight request) before queuing a
            // new one. Otherwise the previous audio leaks and overlaps.
            teardownSpeaking(cache)

            const spokenText = buildSpokenText(summary)
            if (!spokenText) {
                actions.setStatus('listening')
                return
            }
            actions.setStatus('speaking')

            // Store what we're saying so onPartial can match incoming transcripts against it
            // and tell self-transcription bleed apart from real user barge-in.
            cache.spokenTextLower = normaliseForBargeInMatch(spokenText)

            const controller = new AbortController()
            cache.speakAbortController = controller

            try {
                const response = await api.maxHandsFree.synthesize(spokenText, { signal: controller.signal })
                if (!response.ok) {
                    throw new Error(`TTS returned ${response.status}`)
                }
                const audioBlob = await response.blob()
                if (controller.signal.aborted || values.status !== 'speaking') {
                    return
                }
                const url = URL.createObjectURL(audioBlob)
                const audioElement = new Audio(url)
                cache.speakAudioElement = audioElement
                cache.speakAudioUrl = url

                const finished = new Promise<void>((resolve, reject) => {
                    audioElement.onended = () => resolve()
                    audioElement.onerror = () => reject(new Error('audio playback failed'))
                })

                await audioElement.play()
                // Capture once playback has actually started — distinguishes "Max attempted to
                // speak" from "Max successfully voiced a response." Counted per session via
                // assistant_turns on the exit event.
                cache.assistantTurnCount = (cache.assistantTurnCount ?? 0) + 1
                posthog.capture('max hands-free assistant spoke', {
                    text_chars: spokenText.length,
                    viz_count: summary.vizCount,
                })
                await finished
            } catch (err) {
                if ((err as { name?: string }).name !== 'AbortError') {
                    posthog.captureException(err)
                }
            } finally {
                if (cache.speakAbortController === controller) {
                    teardownSpeaking(cache)
                    if (values.status === 'speaking') {
                        actions.setStatus('listening')
                    }
                }
            }
        },

        cancelSpeaking: () => {
            teardownSpeaking(cache)
        },

        interruptSpeaking: () => {
            // Only meaningful while we're actually playing audio — guard against stray
            // fires from elsewhere accidentally jolting us through state transitions.
            if (values.status !== 'speaking') {
                return
            }
            teardownSpeaking(cache)
            actions.setStatus('listening')
            cache.interruptedCount = (cache.interruptedCount ?? 0) + 1
            posthog.capture('max hands-free tts interrupted')
        },
    })),

    afterMount(({ actions, cache }) => {
        // Probe the SDK once on mount so the mic button can decide whether to render itself.
        // We capture failures to PostHog instead of surfacing dev-facing errors to end users.
        // Skip the probe entirely when the feature flag is off — the logic mounts for every
        // Max session, so an unconditional dynamic import would download the SDK chunk for
        // every user even though only flagged users can ever use it.
        if (!posthog.isFeatureEnabled(FEATURE_FLAGS.MAX_HANDS_FREE)) {
            actions.setSdkAvailable(false)
            return
        }
        cache.disposables.add(() => {
            let cancelled = false
            void loadScribeSdk()
                .then((sdk) => {
                    if (cancelled) {
                        return
                    }
                    const available = !!sdk?.Scribe && typeof sdk.Scribe.connect === 'function'
                    if (!available) {
                        posthog.captureException(
                            new Error('handsFree: @elevenlabs/client loaded but Scribe is missing')
                        )
                    }
                    actions.setSdkAvailable(available)
                })
                .catch((err) => {
                    if (cancelled) {
                        return
                    }
                    posthog.captureException(err)
                    actions.setSdkAvailable(false)
                })
            return () => {
                cancelled = true
            }
        }, 'sdkProbe')
    }),
])

// Normalises a string to lowercase letters and digits separated by single spaces. Used to
// match an incoming Scribe partial against the TTS content for self-transcription detection.
function normaliseForBargeInMatch(text: string): string {
    return text
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, ' ')
        .trim()
}

// Short words a gym/walking user is likely to shout to stop Max mid-sentence. These
// always trigger barge-in even though they'd otherwise fall under the too-short or
// substring suppression — a wrong barge-in is recoverable (user just keeps talking),
// a swallowed "stop" is not.
const BARGE_IN_TRIGGER_WORDS: ReadonlySet<string> = new Set(['stop', 'wait', 'cancel', 'no', 'max', 'shh', 'hey'])

export type SuppressionReason = 'too_short' | 'substring' | null

// Returns null when the partial should be treated as real user speech (barge in), or a
// reason string when it should be suppressed as TTS bleed. Callers should emit the
// reason to PostHog so we can measure misfire rate before tuning the heuristic.
export function classifyPartial(spokenLower: string, partialLower: string): SuppressionReason {
    if (!partialLower) {
        return 'too_short'
    }
    if (BARGE_IN_TRIGGER_WORDS.has(partialLower)) {
        return null
    }
    if (partialLower.length < 4) {
        return 'too_short'
    }
    if (spokenLower.includes(partialLower)) {
        return 'substring'
    }
    return null
}

function teardownSpeaking(cache: Record<string, any>): void {
    const controller = cache.speakAbortController as AbortController | undefined
    if (controller) {
        try {
            controller.abort()
        } catch {
            // best-effort
        }
        cache.speakAbortController = undefined
    }
    const audio = cache.speakAudioElement as HTMLAudioElement | undefined
    if (audio) {
        try {
            audio.pause()
            audio.src = ''
        } catch {
            // best-effort
        }
        cache.speakAudioElement = undefined
    }
    if (cache.speakAudioUrl) {
        try {
            URL.revokeObjectURL(cache.speakAudioUrl)
        } catch {
            // best-effort
        }
        cache.speakAudioUrl = undefined
    }
    cache.spokenTextLower = undefined
}
