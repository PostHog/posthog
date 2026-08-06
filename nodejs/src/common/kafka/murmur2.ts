/**
 * Kafka-compatible `murmur2` partitioner: `(murmur2(key) & 0x7fffffff) % partitions`.
 *
 * This is the Kafka-Java / python-kafka default, NOT the CRC32 `consistent_random` default of
 * librdkafka clients (node-rdkafka). The cohort-stream-processor routes a merge to the worker that
 * owns `murmur2(key) mod 64`, so producers feeding it must reproduce this exact math. Mirrors the
 * Rust side at `rust/cohort-stream-processor/src/partitions/partitioner.rs`; both are pinned to the
 * published Kafka test vectors.
 *
 * `Math.imul` + `>>> 0` reproduce Rust's wrapping `u32` arithmetic (`wrapping_mul` and unsigned
 * reinterpretation).
 */

const MURMUR2_SEED = 0x9747b28c
const MURMUR2_M = 0x5bd1e995
const MURMUR2_R = 24

/**
 * Kafka `murmur2` hash. Returns the raw hash as an unsigned 32-bit integer; `murmur2Partition`
 * applies the positivity mask and modulo. For the signed Kafka-vector form, use `murmur2(data) | 0`.
 */
export function murmur2(data: Buffer): number {
    const len = data.length
    let h = (MURMUR2_SEED ^ len) >>> 0

    const nblocks = Math.floor(len / 4)
    for (let block = 0; block < nblocks; block++) {
        const i = block * 4
        let k = (data[i] | (data[i + 1] << 8) | (data[i + 2] << 16) | (data[i + 3] << 24)) >>> 0
        k = Math.imul(k, MURMUR2_M) >>> 0
        k = (k ^ (k >>> MURMUR2_R)) >>> 0
        k = Math.imul(k, MURMUR2_M) >>> 0
        h = Math.imul(h, MURMUR2_M) >>> 0
        h = (h ^ k) >>> 0
    }

    const tail = nblocks * 4
    const remainder = len & 3
    if (remainder >= 3) {
        h = (h ^ (data[tail + 2] << 16)) >>> 0
    }
    if (remainder >= 2) {
        h = (h ^ (data[tail + 1] << 8)) >>> 0
    }
    if (remainder >= 1) {
        h = (h ^ data[tail]) >>> 0
        h = Math.imul(h, MURMUR2_M) >>> 0
    }

    h = (h ^ (h >>> 13)) >>> 0
    h = Math.imul(h, MURMUR2_M) >>> 0
    h = (h ^ (h >>> 15)) >>> 0
    return h >>> 0
}

/**
 * The partition `key` lands on: `(murmur2(key) & 0x7fffffff) % partitionCount`. Mirrors
 * `partitioner.rs::partition_for`. `partitionCount` must be > 0.
 */
export function murmur2Partition(key: string | Buffer, partitionCount: number): number {
    const buffer = Buffer.isBuffer(key) ? key : Buffer.from(key, 'utf8')
    return (murmur2(buffer) & 0x7fffffff) % partitionCount
}
