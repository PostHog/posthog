import { GetItemCommand } from '@aws-sdk/client-dynamodb'
import { PutObjectCommand } from '@aws-sdk/client-s3'
import { Message } from 'node-rdkafka'
import { createDecipheriv, generateKeyPairSync } from 'node:crypto'

import { KafkaProducer } from '~/common/kafka/producer'
import { parseJSON } from '~/common/utils/json-parse'
import { StreamedResponse, fetchStreamed } from '~/common/utils/request'
import { TeamDayKeys } from '~/ingestion/pipelines/sessionreplay/ai-research/v4-keys/team-day-keys'
import type { FetchCandidate } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/collected-urls-record'
import {
    CrawlHistoryItem,
    CrawlHistoryStore,
    configurationCacheKey,
} from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/crawl-history'
import { FetchRunner } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/fetch-runner'
import { ImageFetchTopHogMetrics } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/tophog-metrics'
import { UrlFetchConsumer } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/url-fetch-consumer'
import vector from '~/ingestion/pipelines/sessionreplay/ml-mirror/keys/encryption-vector-v4.json'
import {
    buildFetchRunner,
    buildFrontierPublisher,
    v3HostLimits,
} from '~/servers/ingestion-session-replay-ml-image-fetch-server'
import { buildMlMirrorServerConfig } from '~/servers/ingestion-session-replay-ml-mirror-server'
import { createRecordingTopHog } from '~/tests/helpers/tophog'

import { V4JobAdmission } from './job-admission'
import { V4_IMAGE_FETCH_LANE, v4HostLimits } from './lane'
import { RawImageStore } from './raw-image-store'
import { SharedImageFetcher } from './shared-image-fetcher'

jest.mock('~/common/utils/request', () => ({
    ...jest.requireActual('~/common/utils/request'),
    fetchStreamed: jest.fn(),
}))

const fetchStreamedMock = fetchStreamed as jest.MockedFunction<typeof fetchStreamed>

const NOW_MS = Date.parse('2026-10-15T12:00:00Z')
const PNG = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.from('png body')])
const TEAM_KEYS: Record<string, Buffer> = {
    'team:7': Buffer.from(vector.teamDayKey, 'base64'),
    'team:8': Buffer.alloc(32, 8),
}
const OTHER_HASH = 'B'.repeat(22)

function respond(status: number, headers: Record<string, string> = {}, bytes = Buffer.alloc(0)): StreamedResponse {
    return {
        status,
        headers,
        headerLines: Object.entries(headers).map(([name, value]) => ({ name, value })),
        read: jest.fn().mockResolvedValue({ bytes, overLimit: false }),
        discard: jest.fn(),
    }
}

/** A record in the shape `replay-recorder-v4/src/urls.rs` produces: keyed by registrable domain, with no headers. */
function recorderRecord(jobs: { ref: string; url: string }[]): Message {
    const value = Buffer.from(
        JSON.stringify({
            v: 2,
            jobs: jobs.map(({ ref, url }) => ({
                sessionId: vector.identity.sessionId,
                originalRef: ref,
                currentUrl: url,
                remainingHops: 10,
                notBeforeMs: 0,
                firstSeenAtMs: NOW_MS,
                fetchCount: 0,
                republishCount: 0,
                lastRepublishReason: null,
            })),
        })
    )
    return { value, key: Buffer.from('example.com'), size: value.length, topic: 'v4', partition: 0, offset: 0 }
}

function openFrame(key: Buffer, frame: Buffer): { context: Record<string, unknown>; body: Buffer } {
    const length = frame.readUInt16BE(6)
    const aad = frame.subarray(8, 8 + length)
    const nonce = frame.subarray(8 + length, 20 + length)
    const sealed = frame.subarray(20 + length)
    const decipher = createDecipheriv('aes-256-gcm', key, nonce, { authTagLength: 16 })
    decipher.setAAD(aad)
    decipher.setAuthTag(sealed.subarray(sealed.length - 16))
    const body = Buffer.concat([decipher.update(sealed.subarray(0, sealed.length - 16)), decipher.final()])
    return { context: parseJSON(aad.toString()).context, body }
}

/** The origin's robots.txt and tdmrep.json are known, so the jobs do not wait on one configuration fetch. */
class MemoryCrawlHistory implements CrawlHistoryStore {
    public readonly items = new Map<string, CrawlHistoryItem>(
        (['robots', 'tdmrep'] as const).map((kind) => {
            const origin = new URL(vector.url.url).origin
            const nowMs = Date.now()
            const item: CrawlHistoryItem = {
                kind,
                key: configurationCacheKey(origin, kind),
                origin,
                status: 'absent',
                fetchedAtMs: nowMs,
                refreshAtMs: nowMs + 86_400_000,
                freshUntilMs: nowMs + 86_400_000,
                retryAtMs: nowMs,
                storageExpiresAtMs: nowMs + 86_400_000,
            }
            return [item.key, item]
        })
    )
    read(keys: string[]): Promise<Map<string, CrawlHistoryItem>> {
        return Promise.resolve(
            new Map(keys.flatMap((key) => (this.items.has(key) ? [[key, this.items.get(key)!]] : [])))
        )
    }
    write(items: CrawlHistoryItem[]): Promise<void> {
        items.forEach((item) => this.items.set(item.key, item))
        return Promise.resolve()
    }
}

function lane(rows: Record<string, Record<string, any> | undefined>) {
    const config = buildMlMirrorServerConfig({
        WEB_BOT_AUTH_PRIVATE_KEYS: generateKeyPairSync('ed25519')
            .privateKey.export({ type: 'pkcs8', format: 'pem' })
            .toString(),
    })
    const producer = { produce: jest.fn(() => Promise.resolve()) } as unknown as KafkaProducer
    const publisher = buildFrontierPublisher(producer, 10, V4_IMAGE_FETCH_LANE)
    const dynamo = {
        send: jest.fn((command: GetItemCommand) => {
            const id = `${command.input.Key!.pk.S}/${command.input.Key!.sk.S}`
            return Promise.resolve({ Item: rows[id] })
        }),
    }
    const kms = {
        send: jest.fn((command: any) =>
            Promise.resolve({ Plaintext: TEAM_KEYS[`team:${command.input.EncryptionContext.team_id}`] })
        ),
    }
    const keys = new TeamDayKeys(dynamo, kms, 'keys', 'arn')
    const puts: PutObjectCommand[] = []
    const s3 = {
        send: jest.fn((command: PutObjectCommand) => {
            puts.push(command)
            return Promise.resolve({})
        }),
    }
    const topHog = new ImageFetchTopHogMetrics(createRecordingTopHog().registry)
    const runner = buildFetchRunner(
        config,
        publisher,
        topHog,
        new RawImageStore(keys, s3 as any, 'images-v4', 10),
        v4HostLimits(v3HostLimits(config), config.AI_RESEARCH_REPLAY_V4_IMAGE_FETCH_HOST_BUDGET_SHARE),
        (fetcher) => new SharedImageFetcher(fetcher)
    )
    const admission = new V4JobAdmission(keys, 7)
    const deadLetters = { park: jest.fn(() => Promise.resolve()) }
    const consumer = new UrlFetchConsumer(
        new MemoryCrawlHistory(),
        publisher,
        {
            seenTtlSeconds: config.AI_RESEARCH_IMAGE_FETCH_CRAWL_HISTORY_TTL_SECONDS,
            dryRun: false,
            acceptsRef: V4_IMAGE_FETCH_LANE.acceptsRef,
            admitCandidates: (candidates, nowMs) => admission.admit(candidates, nowMs),
        },
        runner,
        deadLetters,
        topHog
    )
    return { consumer, runner, puts, deadLetters }
}

const row = (team: number, day = vector.identity.keyDay, extra: Record<string, any> = {}) => ({
    [`team:${team}/day:${day}`]: {
        pk: { S: `team:${team}` },
        sk: { S: `day:${day}` },
        wrapped_key: { B: Buffer.from('w') },
        ...extra,
    },
})

describe('v4 image fetch lane', () => {
    const runners: FetchRunner[] = []

    beforeEach(() => {
        fetchStreamedMock.mockReset()
        fetchStreamedMock.mockImplementation((url) =>
            Promise.resolve(
                new URL(url).pathname.endsWith('.png')
                    ? respond(200, { 'content-type': 'image/png' }, PNG)
                    : respond(404)
            )
        )
    })

    afterEach(async () => {
        await Promise.all(runners.splice(0).map((runner) => runner.close()))
    })

    it("stores a recorder record's image under each team's day key, with one request for a URL two teams share", async () => {
        const harness = lane({ ...row(7), ...row(8) })
        runners.push(harness.runner)
        const otherTeamRef = `imageurl:v4:8:${vector.identity.keyDay}:${OTHER_HASH}`

        await harness.consumer.handleBatch(
            [
                recorderRecord([
                    { ref: vector.url.ref, url: vector.url.url },
                    { ref: otherTeamRef, url: vector.url.url },
                ]),
            ],
            NOW_MS
        )

        expect(harness.deadLetters.park).not.toHaveBeenCalled()
        expect(fetchStreamedMock.mock.calls.filter(([url]) => url === vector.url.url)).toHaveLength(1)
        const stored = new Map(harness.puts.map((put) => [put.input.Key, put.input.Body as Buffer]))
        expect([...stored.keys()].sort()).toEqual([
            `images/url/dt=${vector.identity.keyDay}/7/${vector.url.ref.split(':').pop()}`,
            `images/url/dt=${vector.identity.keyDay}/8/${OTHER_HASH}`,
        ])
        for (const [team, ref] of [
            [7, vector.url.ref],
            [8, otherTeamRef],
        ] as const) {
            const objectKey = `images/url/dt=${vector.identity.keyDay}/${team}/${ref.split(':').pop()}`
            const { context, body } = openFrame(TEAM_KEYS[`team:${team}`], stored.get(objectKey)!)
            expect(body).toEqual(PNG)
            expect(context).toEqual({
                teamId: team,
                keyDay: vector.identity.keyDay,
                kind: 'image-url',
                codec: 'none',
                ref,
            })
        }
    })

    it.each([
        ['a day past the raw window', { ...row(7, '2026-10-07') }, `imageurl:v4:7:2026-10-07:${OTHER_HASH}`],
        [
            'a tombstoned team day',
            row(7, vector.identity.keyDay, { deleted: { BOOL: true }, wrapped_key: undefined }),
            vector.url.ref,
        ],
        ['a team day without a key row', {}, vector.url.ref],
    ])('drops a job for %s before any request', async (_name, rows, ref) => {
        const harness = lane(rows)
        runners.push(harness.runner)

        await harness.consumer.handleBatch([recorderRecord([{ ref, url: vector.url.url }])], NOW_MS)

        expect(fetchStreamedMock).not.toHaveBeenCalled()
        expect(harness.puts).toHaveLength(0)
        expect(harness.deadLetters.park).not.toHaveBeenCalled()
    })

    it('starts only a bounded number of key lookups at once, so a batch of many new team days does not time out', async () => {
        let running = 0
        let mostRunning = 0
        const keys = {
            get: async () => {
                running++
                mostRunning = Math.max(mostRunning, running)
                await new Promise((resolve) => setImmediate(resolve))
                running--
                return { status: 'ok' as const, key: Buffer.alloc(32) }
            },
        }
        const candidates = Array.from(
            { length: 100 },
            (_, team) =>
                ({ originalRef: `imageurl:v4:${team + 1}:${vector.identity.keyDay}:${OTHER_HASH}` }) as FetchCandidate
        )

        expect(await new V4JobAdmission(keys, 7).admit(candidates, NOW_MS)).toHaveLength(100)
        expect(mostRunning).toBeLessThanOrEqual(16)
    })
})
