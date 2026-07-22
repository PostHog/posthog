/** Encode already-mapped records into a Snappy/Parquet buffer via an in-memory sink — parquetjs only
 *  writes to a stream, so this is the openStream/collect plumbing. Schema + record shape are the caller's. */
import { ParquetSchema, ParquetWriter } from '@dsnp/parquetjs'
import { Writable } from 'stream'

export async function parquetRecordsToBuffer(
    schema: ParquetSchema,
    records: Record<string, unknown>[]
): Promise<Buffer> {
    const chunks: Buffer[] = []
    const sink = new Writable({
        write(chunk: Buffer, _encoding, callback) {
            chunks.push(chunk)
            callback()
        },
    })
    // parquetjs types want an fs.WriteStream, but it only calls write/end/on at runtime, which Writable provides.
    const writer = await ParquetWriter.openStream(
        schema,
        sink as unknown as Parameters<typeof ParquetWriter.openStream>[1]
    )
    for (const record of records) {
        await writer.appendRow(record)
    }
    await writer.close()
    return Buffer.concat(chunks)
}
