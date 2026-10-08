import { compress, decompress } from '@mongodb-js/zstd'
import avro from 'avsc'
import { Readable } from 'stream'

import { MetricRecord } from './types'

/** zstd level 1, the same level the capture service writes with. */
const ZSTD_COMPRESSION_LEVEL = 1

const zstdEncoders = {
    zstandard: (buf: Buffer, cb: (err: Error | null, out?: Buffer) => void): void => {
        compress(buf, ZSTD_COMPRESSION_LEVEL)
            .then((compressed) => cb(null, compressed))
            .catch(cb)
    },
}

export interface DecodedMetricsPacket {
    /** The writer schema read from the container header. */
    recordType: avro.Type
    /** Hex fingerprint of the writer schema; packets only merge when it matches. */
    schemaFingerprint: string
    /** Codec name from the container header (`null` when uncompressed). */
    codec: string
    records: MetricRecord[]
}

/** Caps applied while a packet decodes, so a highly compressible packet cannot expand without bound. */
export interface MetricsPacketDecodeLimits {
    maxRecords: number
    maxDecompressedBytes: number
}

export class MetricsPacketTooLargeError extends Error {
    override name = 'MetricsPacketTooLargeError'
}

/**
 * Decodes one Avro object container file (the value of a metrics Kafka
 * message) into its rows. The schema comes from the container header, so the
 * decoder never needs the schema compiled in. The decode stops with a
 * `MetricsPacketTooLargeError` as soon as a limit is exceeded, before the
 * remaining blocks inflate.
 */
export function decodeMetricsPacket(buffer: Buffer, limits?: MetricsPacketDecodeLimits): Promise<DecodedMetricsPacket> {
    return new Promise((resolve, reject) => {
        const records: MetricRecord[] = []
        let recordType: avro.Type | undefined
        let codec = 'null'
        let decompressedBytes = 0
        // avsc wraps codec errors, so the cap's own error is kept here to reject with.
        let limitError: MetricsPacketTooLargeError | undefined

        const stream = new Readable()
        const decoder = new avro.streams.BlockDecoder({
            codecs: {
                zstandard: (buf: Buffer, cb: (err: Error | null, out?: Buffer) => void): void => {
                    decompress(buf)
                        .then((inflated) => {
                            decompressedBytes += inflated.length
                            if (limits && decompressedBytes > limits.maxDecompressedBytes) {
                                limitError = new MetricsPacketTooLargeError(
                                    `Metrics packet inflates past ${limits.maxDecompressedBytes} bytes`
                                )
                                cb(limitError)
                                return
                            }
                            cb(null, inflated)
                        })
                        .catch(cb)
                },
            },
        })
        const fail = (error: Error): void => {
            stream.unpipe(decoder)
            decoder.destroy()
            reject(limitError ?? error)
        }

        decoder.on('metadata', (type: avro.Type, containerCodec?: string) => {
            recordType = type
            codec = containerCodec || 'null'
        })
        decoder.on('data', (record: MetricRecord) => {
            if (limits && records.length >= limits.maxRecords) {
                limitError = new MetricsPacketTooLargeError(`Metrics packet has more than ${limits.maxRecords} records`)
                fail(limitError)
                return
            }
            records.push(record)
        })
        decoder.on('end', () => {
            if (recordType === undefined) {
                reject(new Error('Metrics packet has no Avro container header'))
                return
            }
            resolve({
                recordType,
                schemaFingerprint: recordType.fingerprint('md5').toString('hex'),
                codec,
                records,
            })
        })
        decoder.on('error', fail)

        stream.on('error', reject)
        stream.push(buffer)
        stream.push(null)
        stream.pipe(decoder)
    })
}

/** Encodes rows into one Avro object container file with the given writer schema and codec. */
export function encodeMetricsPacket(recordType: avro.Type, codec: string, records: MetricRecord[]): Promise<Buffer> {
    return new Promise((resolve, reject) => {
        const buffers: Buffer[] = []
        const encoder = new avro.streams.BlockEncoder(recordType, { codec, codecs: zstdEncoders })
        encoder.on('error', reject)
        encoder.on('data', (buf: Buffer) => {
            buffers.push(buf)
        })
        encoder.on('end', () => {
            resolve(Buffer.concat(buffers))
        })
        for (const record of records) {
            encoder.write(record)
        }
        encoder.end()
    })
}
