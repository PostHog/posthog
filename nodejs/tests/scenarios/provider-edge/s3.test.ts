import { ProviderEdge, startProviderEdge } from '.'
import { createHash, randomBytes } from 'node:crypto'

import { getDefaultCdpConfig } from '~/cdp/config'
import {
    AttachmentStoreUnavailableError,
    S3AttachmentStore,
    UploadSlot,
    buildAttachmentStore,
} from '~/cdp/services/messaging/attachment-store'
import { InFlightRegistry, requireAdmission } from '~/cdp/services/messaging/in-flight-registry'
import { FetchResponse, internalFetch } from '~/common/utils/request'

import { CardFault, ruleOf } from './faults'

jest.setTimeout(30000)

const config = getDefaultCdpConfig()
const UPSTREAM = config.CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT
const TEAM = 1
const FILE_BYTES = 4096
const PACE_BYTES_PER_SECOND = 8192
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

const elapsedMs = async (work: () => Promise<unknown>): Promise<number> => {
    const started = performance.now()
    await work()
    return performance.now() - started
}

describe('the edge in front of the attachment store', () => {
    let edge: ProviderEdge
    let store: S3AttachmentStore

    const upload = async (uploaded: TestFile): Promise<FetchResponse> => {
        const [slot] = await store.prepareUploads(TEAM, [{ sha256: uploaded.sha256, size: uploaded.sizeBytes }])
        return await put(slot, uploaded.bytes)
    }

    const load = async (stored: TestFile, signal = AbortSignal.timeout(10_000)): Promise<Buffer> => {
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

    test('answers the operation its fault matches with a server error, and passes every other one', async () => {
        const uploaded = file()
        fault({ name: 's3.status', params: { code: 503 }, match: { op: 'get' }, dose: { share: 1 } })

        const answer = await upload(uploaded)
        const loaded = await load(uploaded).catch((error: unknown) => error)

        expect(answer.status).toBe(200)
        expect(loaded).toBeInstanceOf(AttachmentStoreUnavailableError)
    })

    test('stops answering a stalled request, so the caller times out', async () => {
        const uploaded = file()
        await upload(uploaded)
        fault({ name: 's3.stall', match: { op: 'get' }, dose: { count: 1 } })

        const loaded = await load(uploaded, AbortSignal.timeout(CALL_TIMEOUT_MS)).catch((error: unknown) => error)

        expect(loaded).toBeInstanceOf(AttachmentStoreUnavailableError)
        expect(await load(uploaded)).toEqual(uploaded.bytes)
    })

    test.each([
        ['an upload', 'put' as const, (uploaded: TestFile) => upload(uploaded)],
        ['a download', 'get' as const, (uploaded: TestFile) => load(uploaded)],
    ])('paces the body of %s to its byte rate', async (_, op, transfer) => {
        const uploaded = file()
        if (op === 'get') {
            await upload(uploaded)
        }
        fault({ name: 's3.slow', params: { bytesPerSecond: PACE_BYTES_PER_SECOND }, match: { op } })

        const tookMs = await elapsedMs(() => transfer(uploaded))

        expect(tookMs).toBeGreaterThanOrEqual(((FILE_BYTES / PACE_BYTES_PER_SECOND) * 1000) / 2)
        expect(await load(uploaded)).toEqual(uploaded.bytes)
    })
})
