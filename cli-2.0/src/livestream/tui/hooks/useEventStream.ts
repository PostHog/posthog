import { useState, useEffect, useCallback, useRef } from 'react'
import { streamEvents } from '../../sse-client.js'
import type { EventMsg, GeoEventMsg, LivestreamCredentials } from '../../types.js'

type StreamState = 'connecting' | 'connected' | 'reconnecting' | 'disconnected' | 'paused'

type UseEventStreamOptions = {
  credentials: LivestreamCredentials
  eventType?: string
  distinctId?: string
  geo?: boolean
  maxEvents?: number
}

type UseEventStreamReturn = {
  events: EventMsg[]
  geoEvents: GeoEventMsg[]
  state: StreamState
  eventsPerMinute: number
  pause: () => void
  resume: () => void
  clear: () => void
  isPaused: boolean
}

const MAX_EVENTS = 200
const RATE_WINDOW_SECONDS = 60

export const useEventStream = (options: UseEventStreamOptions): UseEventStreamReturn => {
  const { credentials, eventType, distinctId, geo, maxEvents = MAX_EVENTS } = options

  const [events, setEvents] = useState<EventMsg[]>([])
  const [geoEvents, setGeoEvents] = useState<GeoEventMsg[]>([])
  const [state, setState] = useState<StreamState>('connecting')
  const [isPaused, setIsPaused] = useState(false)
  const [eventsPerMinute, setEventsPerMinute] = useState(0)

  const abortControllerRef = useRef<AbortController | null>(null)
  const rateBucketsRef = useRef<number[]>([])
  const eventsThisSecondRef = useRef(0)

  // Rate calculation - update every second
  useEffect(() => {
    const interval = setInterval(() => {
      rateBucketsRef.current.push(eventsThisSecondRef.current)
      eventsThisSecondRef.current = 0

      // Keep only last 60 seconds
      if (rateBucketsRef.current.length > RATE_WINDOW_SECONDS) {
        rateBucketsRef.current.shift()
      }

      // Calculate rate
      const total = rateBucketsRef.current.reduce((a, b) => a + b, 0)
      const rate = Math.round((total / rateBucketsRef.current.length) * 60)
      setEventsPerMinute(rate)
    }, 1000)

    return () => clearInterval(interval)
  }, [])

  const startStream = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }

    abortControllerRef.current = new AbortController()
    setState('connecting')

    try {
      const stream = streamEvents(
        credentials.livestreamHost,
        credentials.token,
        { eventType, distinctId, geo },
        abortControllerRef.current.signal
      )

      setState('connected')

      for await (const event of stream) {
        if (isPaused) continue

        eventsThisSecondRef.current++

        if (geo || 'lat' in event) {
          setGeoEvents((prev) => {
            const next = [event as GeoEventMsg, ...prev]
            return next.slice(0, maxEvents)
          })
        } else {
          setEvents((prev) => {
            const next = [event as EventMsg, ...prev]
            return next.slice(0, maxEvents)
          })
        }
      }
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        return
      }
      setState('disconnected')

      // Auto-reconnect after 2 seconds
      setTimeout(() => {
        if (!isPaused) {
          setState('reconnecting')
          startStream()
        }
      }, 2000)
    }
  }, [credentials, eventType, distinctId, geo, maxEvents, isPaused])

  useEffect(() => {
    if (!isPaused) {
      startStream()
    }

    return () => {
      abortControllerRef.current?.abort()
    }
  }, [startStream, isPaused])

  const pause = useCallback(() => {
    setIsPaused(true)
    setState('paused')
    abortControllerRef.current?.abort()
  }, [])

  const resume = useCallback(() => {
    setIsPaused(false)
    startStream()
  }, [startStream])

  const clear = useCallback(() => {
    setEvents([])
    setGeoEvents([])
    rateBucketsRef.current = []
    eventsThisSecondRef.current = 0
    setEventsPerMinute(0)
  }, [])

  return {
    events,
    geoEvents,
    state,
    eventsPerMinute,
    pause,
    resume,
    clear,
    isPaused,
  }
}
