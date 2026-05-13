import { createParser, type EventSourceMessage } from 'eventsource-parser'
import type { EventMsg, GeoEventMsg } from './types.js'

type StreamOptions = {
  eventType?: string
  distinctId?: string
  geo?: boolean
}

export async function* streamEvents(
  host: string,
  token: string,
  options: StreamOptions,
  signal: AbortSignal
): AsyncGenerator<EventMsg | GeoEventMsg> {
  const params = new URLSearchParams()
  if (options.eventType) params.set('eventType', options.eventType)
  if (options.distinctId) params.set('distinctId', options.distinctId)
  if (options.geo) params.set('geo', 'true')

  const url = `${host}/events${params.size ? '?' + params : ''}`

  const response = await fetch(url, {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'text/event-stream',
    },
    signal,
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`)
  }

  if (!response.body) {
    throw new Error('No response body')
  }

  // Use a queue to bridge callback-based parser to async generator
  const queue: (EventMsg | GeoEventMsg)[] = []
  let resolveWait: (() => void) | null = null
  let streamEnded = false
  let streamError: Error | null = null

  const parser = createParser({
    onEvent: (event: EventSourceMessage) => {
      if (event.data) {
        try {
          queue.push(JSON.parse(event.data))
          resolveWait?.()
        } catch {
          // Skip malformed JSON
        }
      }
    },
  })

  const reader = response.body.getReader()
  const decoder = new TextDecoder()

  // Read loop in background - errors are captured and propagated to the generator
  const readLoop = async () => {
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        parser.feed(decoder.decode(value, { stream: true }))
      }
    } catch (err) {
      // Capture error to propagate to generator, unless it's an abort
      if (err instanceof Error && err.name !== 'AbortError') {
        streamError = err
      }
    } finally {
      streamEnded = true
      resolveWait?.()
    }
  }

  // Start reading in background - don't await, but handle errors via streamError
  readLoop()

  // Yield events as they arrive
  while (!streamEnded || queue.length > 0) {
    // Check for errors before yielding
    if (streamError) {
      throw streamError
    }

    if (queue.length > 0) {
      yield queue.shift()!
    } else if (!streamEnded) {
      await new Promise<void>((r) => {
        resolveWait = r
      })
    }
  }

  // Final error check after stream ends
  if (streamError) {
    throw streamError
  }
}
