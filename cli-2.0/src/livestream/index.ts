import type { LivestreamOptions } from './types.js'
import { authenticate } from './auth.js'
import { streamEvents } from './sse-client.js'

export const runLivestream = async (options: LivestreamOptions): Promise<void> => {
  const creds = await authenticate({
    token: options.token,
    host: options.host,
    livestreamHost: options.livestreamHost,
  })

  if (creds.teamName) {
    console.error(`Connected to ${creds.livestreamHost} (team: ${creds.teamName})`)
  } else {
    console.error(`Connected to ${creds.livestreamHost}`)
  }

  const controller = new AbortController()

  process.on('SIGINT', () => {
    controller.abort()
    process.exit(0)
  })

  try {
    for await (const event of streamEvents(
      creds.livestreamHost,
      creds.token,
      { eventType: options.eventType, distinctId: options.distinctId, geo: options.geo },
      controller.signal
    )) {
      console.log(JSON.stringify(event))
    }
  } catch (err) {
    if ((err as Error).name === 'AbortError') {
      // Normal exit via Ctrl+C
      return
    }
    throw err
  }
}
