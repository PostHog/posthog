import { compress, decompress } from '@mongodb-js/zstd'
import avro from 'avsc'
import { randomBytes } from 'crypto'

// Decoded with wrapped unions: a nullable field holds `null` or a one-key object such as `{ long: 5n }`.
export type MetricRecord = Record<string, unknown>

export interface DecodedMetricRecords {
    type: avro.Type
    meta: Record<string, Buffer>
    codec: string
    records: MetricRecord[]
    decodedBytes: number
}

export class DecodedBytesLimitError extends Error {}

const SUPPORTED_CODECS = new Set(['null', 'zstandard'])

// avsc throws on a long outside the safe integer range, and `series_fingerprint` is a 64-bit hash.
const BIGINT_LONG = avro.types.LongType.__with({
    fromBuffer: (buf: Buffer): bigint => buf.readBigInt64LE(),
    toBuffer: (value: bigint): Buffer => {
        const buf = Buffer.alloc(8)
        buf.writeBigInt64LE(value)
        return buf
    },
    fromJSON: (value: string | number): bigint => BigInt(value),
    toJSON: (value: bigint): string => value.toString(),
    isValid: (value: unknown): boolean => typeof value === 'bigint',
    compare: (a: bigint, b: bigint): number => (a === b ? 0 : a < b ? -1 : 1),
})

// An unwrapped union picks its branch from the JS type of the value and has no branch for a bigint.
export function parseWriterSchema(schema: avro.Schema): avro.Type {
    return avro.Type.forSchema(schema, {
        wrapUnions: true,
        typeHook: (node) =>
            node === 'long' ||
            (typeof node === 'object' && node !== null && (node as { type?: unknown }).type === 'long')
                ? BIGINT_LONG
                : undefined,
    })
}

const HEADER_TYPE = avro.Type.forSchema({
    type: 'record',
    name: 'org.apache.avro.file.Header',
    fields: [
        { name: 'magic', type: { type: 'fixed', name: 'Magic', size: 4 } },
        { name: 'meta', type: { type: 'map', values: 'bytes' } },
        { name: 'sync', type: { type: 'fixed', name: 'Sync', size: 16 } },
    ],
})
const MAGIC = Buffer.from('Obj\x01', 'latin1')
const LONG_TYPE = avro.Type.forSchema('long')

export function unwrap<T>(value: unknown): T | null {
    if (value === null || value === undefined) {
        return null
    }
    if (typeof value === 'object' && !Array.isArray(value) && !Buffer.isBuffer(value)) {
        const branches = Object.values(value)
        return branches.length === 1 ? (branches[0] as T) : null
    }
    return value as T
}

export function isSupportedCodec(codec: string): boolean {
    return SUPPORTED_CODECS.has(codec)
}

export function decodeMetricRecords(
    buffer: Buffer,
    maxDecodedBytes = Number.POSITIVE_INFINITY
): Promise<DecodedMetricRecords> {
    return new Promise((resolve, reject) => {
        try {
            const records: MetricRecord[] = []
            let header: { type: avro.Type; meta: Record<string, Buffer>; codec: string } | undefined
            let decodedBytes = 0
            const countBlock = (block: Buffer, cb: (err: Error | null, inflated?: Buffer) => void): void => {
                decodedBytes += block.length
                if (decodedBytes > maxDecodedBytes) {
                    cb(new DecodedBytesLimitError(`decoded more than ${maxDecodedBytes} bytes`))
                    return
                }
                cb(null, block)
            }
            // avsc requests every block at once, so inflate one at a time and stop at the limit.
            let inflating: Promise<void> = Promise.resolve()
            const inflate = (buf: Buffer, cb: (err: Error | null, inflated?: Buffer) => void): void => {
                inflating = inflating.then(async () => {
                    if (decodedBytes > maxDecodedBytes) {
                        cb(new DecodedBytesLimitError(`decoded more than ${maxDecodedBytes} bytes`))
                        return
                    }
                    try {
                        countBlock(await decompress(buf), cb)
                    } catch (err) {
                        cb(err as Error)
                    }
                })
            }

            // Custom codecs replace the avsc defaults, so `null` must be listed too.
            const decoder = new avro.streams.BlockDecoder({
                parseHook: parseWriterSchema,
                codecs: {
                    null: countBlock,
                    zstandard: inflate,
                },
            })
            decoder.on(
                'metadata',
                (type: avro.Type, codec: string | undefined, meta: { meta: Record<string, Buffer> }) => {
                    header = { type, meta: meta.meta, codec: codec || 'null' }
                }
            )
            decoder.on('data', (record: MetricRecord) => {
                records.push(record)
            })
            decoder.on('end', () => {
                if (header === undefined) {
                    reject(new Error('No metadata found'))
                    return
                }
                const decoded = { ...header, records, decodedBytes }
                void inflating.then(() => resolve(decoded))
            })
            decoder.on('error', (err) => void inflating.then(() => reject(err)))
            decoder.end(buffer)
        } catch (err) {
            reject(err)
        }
    })
}

// avsc's `BlockEncoder` drops `logicalType: timestamp-micros`, which ClickHouse needs, so keep the header.
export async function encodeMetricRecords(
    container: Pick<DecodedMetricRecords, 'type' | 'meta' | 'codec'>,
    records: MetricRecord[]
): Promise<Buffer> {
    if (!isSupportedCodec(container.codec)) {
        throw new Error(`Unsupported Avro codec: ${container.codec}`)
    }
    const sync = randomBytes(16)
    const header = HEADER_TYPE.toBuffer({
        magic: MAGIC,
        meta: { ...container.meta, 'avro.codec': Buffer.from(container.codec) },
        sync,
    })
    const body = Buffer.concat(records.map((record) => container.type.toBuffer(record)))
    const data = container.codec === 'zstandard' ? await compress(body, 1) : body
    return Buffer.concat([header, LONG_TYPE.toBuffer(records.length), LONG_TYPE.toBuffer(data.length), data, sync])
}
