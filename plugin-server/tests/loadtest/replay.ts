import { PostHog } from 'posthog-node'

import snapshotsJson from '../../tests/main/ingestion-queues/session-recording/data/snapshot-full.json'

const {
    POSTHOG_HOST = 'http://127.0.0.1:8000',
    POSTHOG_PROJECT_KEY,
    SESSION_COUNT = '10000',
    RPS = '100',
} = process.env

const rps = parseInt(RPS)
const sessionCount = parseInt(SESSION_COUNT)

// This will hammer posthog with requests, so be careful
// We will create N number of sesssions and just constantly send traffic to it...

if (!POSTHOG_PROJECT_KEY) {
    throw new Error('POSTHOG_PROJECT_KEY is not set')
}

const posthog = new PostHog(POSTHOG_PROJECT_KEY, {
    host: POSTHOG_HOST,
})

posthog.on('error', (error) => {
    console.error(error)
})

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))
let shuttingdown = false

const createSessionId = () => `test-sessions-${Math.round(Math.random() * sessionCount)}`

const main = async () => {
    while (!shuttingdown) {
        const start = Date.now()

        // Iterate for rps count and send events
        for (let i = 0; i < rps; i++) {
            const sessionId = createSessionId()
            const clonedSnapshot = { ...snapshotsJson }
            clonedSnapshot.timestamp = Date.now()
            posthog.capture({
                event: '$snapshot',
                distinctId: sessionId,
                properties: {
                    distinct_id: sessionId,
                    $snapshot_data: [clonedSnapshot],
                    $session_id: sessionId,
                    $window_id: sessionId,
                },
            })
        }
        console.log(`Sent ${RPS} events`)

        const duration = Date.now() - start

        await wait(Math.max(0, 1000 - duration))
    }
}

main()
    .then(() => {
        console.log('done')
    })
    .catch((error) => {
        console.error(error)
    })

// catch exit and wait for all requests to finish
process.on('SIGINT', async () => {
    shuttingdown = true
    console.log('Caught interrupt signal')
    await posthog.shutdownAsync()
    process.exit()
})
