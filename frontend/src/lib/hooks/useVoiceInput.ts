import { useCallback, useEffect, useRef, useState } from 'react'

export interface UseVoiceInputOptions {
    onTranscript?: (transcript: string) => void
    continuous?: boolean
    lang?: string
}

export interface UseVoiceInputReturn {
    isListening: boolean
    isSupported: boolean
    transcript: string
    error: string | null
    startListening: () => void
    stopListening: () => void
    toggleListening: () => void
}

// Type definitions for Web Speech API
interface SpeechRecognitionEvent extends Event {
    results: SpeechRecognitionResultList
    resultIndex: number
}

interface SpeechRecognitionResultList {
    length: number
    item(index: number): SpeechRecognitionResult
    [index: number]: SpeechRecognitionResult
}

interface SpeechRecognitionResult {
    length: number
    item(index: number): SpeechRecognitionAlternative
    [index: number]: SpeechRecognitionAlternative
    isFinal: boolean
}

interface SpeechRecognitionAlternative {
    transcript: string
    confidence: number
}

interface SpeechRecognitionErrorEvent extends Event {
    error: string
    message: string
}

interface SpeechRecognition extends EventTarget {
    continuous: boolean
    interimResults: boolean
    lang: string
    onresult: ((event: SpeechRecognitionEvent) => void) | null
    onerror: ((event: SpeechRecognitionErrorEvent) => void) | null
    onend: (() => void) | null
    onstart: (() => void) | null
    start(): void
    stop(): void
    abort(): void
}

interface SpeechRecognitionConstructor {
    new (): SpeechRecognition
}

declare global {
    interface Window {
        SpeechRecognition?: SpeechRecognitionConstructor
        webkitSpeechRecognition?: SpeechRecognitionConstructor
    }
}

function getSpeechRecognition(): SpeechRecognitionConstructor | undefined {
    if (typeof window === 'undefined') {
        return undefined
    }
    return window.SpeechRecognition || window.webkitSpeechRecognition
}

export function useVoiceInput(options: UseVoiceInputOptions = {}): UseVoiceInputReturn {
    const { onTranscript, continuous = false, lang = 'en-US' } = options

    const [isListening, setIsListening] = useState(false)
    const [transcript, setTranscript] = useState('')
    const [error, setError] = useState<string | null>(null)

    const recognitionRef = useRef<SpeechRecognition | null>(null)
    const SpeechRecognitionClass = getSpeechRecognition()
    const isSupported = !!SpeechRecognitionClass

    const startListening = useCallback(() => {
        if (!SpeechRecognitionClass) {
            setError('Speech recognition is not supported in this browser')
            return
        }

        // Clean up existing recognition instance first
        if (recognitionRef.current) {
            recognitionRef.current.abort()
            recognitionRef.current = null
        }

        setError(null)
        setTranscript('')

        const recognition = new SpeechRecognitionClass()

    const stopListening = useCallback(() => {
        if (recognitionRef.current) {
            recognitionRef.current.stop()
            recognitionRef.current = null
        }
        setIsListening(false)
    }, [])

    const toggleListening = useCallback(() => {
        if (isListening) {
            stopListening()
        } else {
            startListening()
        }
    }, [isListening, startListening, stopListening])

    useEffect(() => {
        return () => {
            if (recognitionRef.current) {
                recognitionRef.current.abort()
                recognitionRef.current = null
            }
        }
    }, [])

    return {
        isListening,
        isSupported,
        transcript,
        error,
        startListening,
        stopListening,
        toggleListening,
    }
}
