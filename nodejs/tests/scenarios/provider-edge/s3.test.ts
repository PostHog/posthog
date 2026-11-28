import { ProviderEdge, startProviderEdge } from '.'
import { createHash, randomBytes } from 'node:crypto'
import { once } from 'node:events'
import http from 'node:http'
import { AddressInfo } from 'node:net'

import { getDefaultCdpConfig } from '~/cdp/config'
import {
    AttachmentStoreUnavailableError,
    S3AttachmentStore,
    UploadSlot,
    buildAttachmentStore,
} from '~/cdp/services/messaging/attachment-store'
import { InFlightRegistry, requireAdmission } from '~/cdp/services/messaging/in-flight-registry'
import { FetchResponse, internalFetch } from '~/common/utils/request'
import { waitForExpect } from '~/tests/helpers/expectations'

import { CardFault, ruleOf } from './faults'
import { paced } from './s3'

jest.setTimeout(30000)

const config = getDefaultCdpConfig()
const UPSTREAM = config.CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT
const TEAM = 1
const FILE_BYTES = 4096
const PACE_BYTES_PER_SECOND = 1_000_000
const PACED_BYTES_PER_SECOND = 40_000
const CALL_TIMEOUT_MS = 500

type TestFile = { bytes: Buffer; sha256: string; sizeBytes: number; filename: string; contentType: string }

const file = (): TestFile => {
    const bytes = randomBytes(FILE_BYTES)
    return {
        bytes,
        sha256: createHash('sha256').update(bytes).digest('hex'),
        sizeBytes: bytes.length,
        filename: 'invoice.pdf',
        contentType: 'application/pdf',
    }
}

const put = (slot: UploadSlot, body: Buffer): Promise<FetchResponse> => {
    if (slot.status !== 'upload') {
        throw new Error(`expected an upload slot, got ${slot.status}`)
    }
    return internalFetch(slot.url, { method: slot.method, headers: slot.headers, body })
}

const roomForAnySend = new InFlightRegistry({
    budgetBytes: Number.MAX_SAFE_INTEGER,
    heapLimitBytes: Number.MAX_SAFE_INTEGER,
    maxInFlight: Number.MAX_SAFE_INTEGER,
})

describe('the edge in front of the attachment store', () => {
    let edge: ProviderEdge
    let store: S3AttachmentStore

    const upload = async (uploaded: TestFile): Promise<FetchResponse> => {
        const [slot] = await store.prepareUploads(TEAM, [{ sha256: uploaded.sha256, size: uploaded.sizeBytes }])
        return await put(slot, uploaded.bytes)
    }

    const load = async (stored: TestFile, signal = new AbortController().signal): Promise<Buffer> => {
        const { started } = roomForAnySend.tryStart([stored], () =>
            store.load(TEAM, requireAdmission([stored]), signal)
        ) as { started: ReturnType<S3AttachmentStore['load']> }
        const [loaded] = await started
        return Buffer.from(loaded.bytes)
    }

    const fault = (cardFault: CardFault): string => edge.addFault(ruleOf(cardFault))

    beforeEach(async () => {
        edge = await startProviderEdge({ port: 0 })
        const endpoint = await edge.s3ProxyOf(UPSTREAM)
        store = buildAttachmentStore({
            ...config,
            CDP_EMAIL_ATTACHMENTS_S3_PREFIX: `scenario-edge-test/${Date.now()}`,
            CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT: endpoint,
            CDP_EMAIL_ATTACHMENTS_S3_TIMEOUT_MS: CALL_TIMEOUT_MS,
        })!
    })

    afterEach(async () => {
        await edge.close()
    })

    test('passes a signed upload and its download through unchanged', async () => {
        const uploaded = file()

        const answer = await upload(uploaded)

        expect(answer.status).toBe(200)
        expect(await load(uploaded)).toEqual(uploaded.bytes)
    })

    test.each<[string, CardFault[]]>([
        ['alone', []],
        ['behind a slowed store', [{ name: 's3.slow', params: { bytesPerSecond: PACE_BYTES_PER_SECOND } }]],
    ])(
        'answers the operation its fault matches with a server error %s, and passes every other one',
        async (_, before) => {
            const uploaded = file()
            before.forEach(fault)
            fault({ name: 's3.status', params: { code: 503 }, match: { op: 'get' }, dose: { share: 1 } })

            const answer = await upload(uploaded)
            const loaded = await load(uploaded).catch((error: unknown) => error)

            expect(answer.status).toBe(200)
            expect(loaded).toBeInstanceOf(AttachmentStoreUnavailableError)
        }
    )

    test('holds a stalled request open until the caller gives up, and passes the next one', async () => {
        const uploaded = file()
        await upload(uploaded)
        const stall = fault({ name: 's3.stall', match: { op: 'get' }, dose: { count: 1 } })
        const caller = new AbortController()

        let settledBeforeAbort = false
        const stalled = load(uploaded, caller.signal).catch((error: unknown) => error)
        void stalled.then(() => (settledBeforeAbort = !caller.signal.aborted))
        await waitForExpect(() => expect(edge.firstAppliedAt(stall)).toBeDefined(), 5000, 5)
        caller.abort()

        expect({ failed: await stalled, settledBeforeAbort }).toEqual({
            failed: expect.any(AttachmentStoreUnavailableError),
            settledBeforeAbort: false,
        })
        expect(await load(uploaded)).toEqual(uploaded.bytes)
    })

    test('keeps a counted server error for the next upload when one hangs up before its body ends', async () => {
        const uploaded = file()
        const status = fault({ name: 's3.status', params: { code: 503 }, match: { op: 'put' }, dose: { count: 1 } })
        const [slot] = await store.prepareUploads(TEAM, [{ sha256: uploaded.sha256, size: uploaded.sizeBytes }])
        if (slot.status !== 'upload') {
            throw new Error(`expected an upload slot, got ${slot.status}`)
        }
        const partial = http.request(slot.url, {
            method: slot.method,
            headers: { ...slot.headers, expect: '100-continue' },
        })
        partial.on('error', () => undefined)
        partial.flushHeaders()
        await once(partial, 'continue')
        partial.write(uploaded.bytes.subarray(0, FILE_BYTES / 2))
        partial.destroy()

        const answer = await upload(uploaded)

        expect({ status: answer.status, answered: edge.firstAppliedAt(status) !== undefined }).toEqual({
            status: 503,
            answered: true,
        })
    })

    test('passes an upload whose server error was released before its body ended', async () => {
        const uploaded = file()
        const status = fault({ name: 's3.status', params: { code: 503 }, match: { op: 'put' }, dose: { share: 1 } })
        const [slot] = await store.prepareUploads(TEAM, [{ sha256: uploaded.sha256, size: uploaded.sizeBytes }])
        if (slot.status !== 'upload') {
            throw new Error(`expected an upload slot, got ${slot.status}`)
        }
        const upload = http.request(slot.url, {
            method: slot.method,
            headers: { ...slot.headers, expect: '100-continue' },
        })
        const answered = once(upload, 'response') as Promise<[http.IncomingMessage]>
        upload.flushHeaders()
        await once(upload, 'continue')
        upload.write(uploaded.bytes.subarray(0, FILE_BYTES / 2))
        edge.removeFault(status)
        upload.end(uploaded.bytes.subarray(FILE_BYTES / 2))
        const [answer] = await answered
        answer.resume()

        expect({ status: answer.statusCode, answered: edge.firstAppliedAt(status) }).toEqual({
            status: 200,
            answered: undefined,
        })
    })

    test('drops its call to the store when the caller hangs up first, and passes the next call', async () => {
        const held: http.IncomingMessage[] = []
        const slowStore = http.createServer((req, res) => {
            if (req.url === '/held') {
                held.push(req)
                return
            }
            res.end('next')
        })
        await new Promise<void>((resolve) => slowStore.listen(0, '127.0.0.1', resolve))
        try {
            const proxy = await edge.s3ProxyOf(`http://127.0.0.1:${(slowStore.address() as AddressInfo).port}/`)

            const caller = new AbortController()
            const hungUp = new Promise<string>((resolve) => {
                http.get(`${proxy}/held`, { signal: caller.signal }).on('error', (error) => resolve(error.name))
            })
            await waitForExpect(() => expect(held).toHaveLength(1), 5000, 5)
            caller.abort()
            await waitForExpect(() => expect(held.map((call) => call.destroyed)).toEqual([true]), 5000, 5)
            const next = await internalFetch(`${proxy}/next`)

            expect({ hungUp: await hungUp, next: await next.text() }).toEqual({ hungUp: 'AbortError', next: 'next' })
        } finally {
            slowStore.closeAllConnections()
            await new Promise((resolve) => slowStore.close(resolve))
        }
    })

    test.each([
        ['an upload', 'put' as const, (uploaded: TestFile) => upload(uploaded)],
        ['a download', 'get' as const, (uploaded: TestFile) => load(uploaded)],
    ])('passes the paced body of %s intact, and counts the pace observed', async (_, op, transfer) => {
        const uploaded = file()
        if (op === 'get') {
            await upload(uploaded)
        }
        const slow = fault({ name: 's3.slow', params: { bytesPerSecond: PACED_BYTES_PER_SECOND }, match: { op } })

        const startedAt = performance.now()
        await transfer(uploaded)
        const tookMs = performance.now() - startedAt

        expect({
            observed: edge.firstAppliedAt(slow) !== undefined,
            heldToItsPace: tookMs >= 0.9 * (FILE_BYTES / PACED_BYTES_PER_SECOND) * 1000,
        }).toEqual({ observed: true, heldToItsPace: true })
        expect(await load(uploaded)).toEqual(uploaded.bytes)
    })

    test('counts a slowed store observed only once it holds back a body, not on a HEAD with none', async () => {
        const uploaded = file()
        await upload(uploaded)
        const slow = fault({ name: 's3.slow', params: { bytesPerSecond: PACE_BYTES_PER_SECOND } })
        await internalFetch(`${await edge.s3ProxyOf(UPSTREAM)}/scenario-edge-missing-bucket/missing-key`, {
            method: 'HEAD',
        })
        const afterHead = edge.firstAppliedAt(slow)
        await load(uploaded)

        expect({ afterHead, afterGet: edge.firstAppliedAt(slow) }).toEqual({
            afterHead: undefined,
            afterGet: expect.any(Number),
        })
    })

    test.each(['https://store.example.com', 'http://localhost:19000/s3', 'http://[::1]:19000'])(
        'refuses to stand in front of %s, which it cannot reach as the client would',
        async (upstream) => {
            await expect(edge.s3ProxyOf(upstream)).rejects.toThrow(
                'the S3 edge forwards only to a plain HTTP store at its root'
            )
        }
    )

    test('releases a paced body one slice a tenth of a second, and leaves no timer once its reader hangs up', async () => {
        jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask'] })
        try {
            const pace = paced(1000, () => undefined)
            const received: number[] = []
            pace.on('data', (slice: Buffer) => received.push(slice.length))

            pace.write(Buffer.alloc(350))
            await jest.advanceTimersByTimeAsync(100)
            const afterOneTenth = [...received]
            await jest.advanceTimersByTimeAsync(200)
            pace.destroy()

            expect({ afterOneTenth, received, timers: jest.getTimerCount() }).toEqual({
                afterOneTenth: [100],
                received: [100, 100, 100],
                timers: 0,
            })
        } finally {
            jest.useRealTimers()
        }
    })
})
