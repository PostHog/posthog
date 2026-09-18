import { compress, decompress } from '@mongodb-js/zstd'
import avro from 'avsc'
import { Readable } from 'stream'

import { MetricRecord } from './types'

/** zstd level 1, the same level the capture service writes with. */
const ZSTD_COMPRESSION_LEVEL = 1

const zstdCodecs = {
    zstandard: (buf: Buffer, cb: (err: Error | null, out?: Buffer) => void): void => {
        decompress(buf)
            .then((inflated) => cb(null, inflated))
            .catch(cb)
    },
}

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

/**
 * Decodes one Avro object container file (the value of a metrics Kafka
 * message) into its rows. The schema comes from the container header, so the
 * decoder never needs the schema compiled in.
 */
export function decodeMetricsPacket(buffer: Buffer): Promise<DecodedMetricsPacket> {
    return new Promise((resolve, reject) => {
        const records: MetricRecord[] = []
        let recordType: avro.Type | undefined
        let codec = 'null'

        const decoder = new avro.streams.BlockDecoder({ codecs: zstdCodecs })
        decoder.on('metadata', (type: avro.Type, containerCodec?: string) => {
            recordType = type
            codec = containerCodec || 'null'
        })
        decoder.on('data', (record: MetricRecord) => {
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
        decoder.on('error', reject)

        const stream = new Readable()
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
