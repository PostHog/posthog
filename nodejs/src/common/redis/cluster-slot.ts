/**
 * Standard Redis cluster CRC16 (XMODEM polynomial 0x1021) and slot mapping.
 *
 * Used by multi-key Lua scripts that need to group keys by their cluster slot
 * before dispatch — Redis Cluster (and Valkey Serverless) rejects EVAL/EVALSHA
 * with `CROSSSLOT` when the keys span multiple slots.
 *
 * Hash-tag aware: keys containing `{tag}` are hashed by the tag content only,
 * matching the Redis cluster spec.
 */
const CRC16_TABLE = new Uint16Array(256)
for (let i = 0; i < 256; i++) {
    let crc = i << 8
    for (let j = 0; j < 8; j++) {
        crc = crc & 0x8000 ? (crc << 1) ^ 0x1021 : crc << 1
    }
    CRC16_TABLE[i] = crc & 0xffff
}

function crc16(s: string): number {
    let crc = 0
    for (let i = 0; i < s.length; i++) {
        crc = ((crc << 8) ^ CRC16_TABLE[((crc >> 8) ^ s.charCodeAt(i)) & 0xff]) & 0xffff
    }
    return crc
}

export function calculateSlot(key: string): number {
    const open = key.indexOf('{')
    if (open >= 0) {
        const close = key.indexOf('}', open + 1)
        if (close > open + 1) {
            return crc16(key.slice(open + 1, close)) % 16384
        }
    }
    return crc16(key) % 16384
}
