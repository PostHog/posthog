import { SymbolDataType } from '@/error-tracking/container'

import { SMALL_MAPPING } from './fixtures'
import { writeSymbolData, writeZip as zip } from './symbol-set-writer'

// The payload of a SourceAndMap symbol set: each part after its length as a little-endian u64.
function sourceAndMapPayload(source: Uint8Array, map: Uint8Array): Buffer {
    const sourceLength = Buffer.alloc(8)
    sourceLength.writeBigUInt64LE(BigInt(source.length))
    const mapLength = Buffer.alloc(8)
    mapLength.writeBigUInt64LE(BigInt(map.length))
    return Buffer.concat([sourceLength, source, mapLength, map])
}

// Stored symbol sets for the extract and download scenarios. Both CLIs only read them.

const v1 = (type: SymbolDataType, payload: string): Buffer =>
    Buffer.concat([
        Buffer.from('posthog_error_tracking'),
        Buffer.from([1, 0, 0, 0, type, 0, 0, 0]),
        Buffer.from(payload),
    ])

export const SYMBOL_SETS: Record<string, Uint8Array> = {
    'app.js.map.bin': writeSymbolData(
        SymbolDataType.SourceAndMap,
        sourceAndMapPayload(
            Buffer.from('a();\n//# chunkId=x'),
            Buffer.from('{"version":3,"sources":["a.ts"],"names":[],"mappings":"AAAA"}')
        )
    ),
    'index.hbc.map.bin': writeSymbolData(
        SymbolDataType.HermesMap,
        Buffer.from('{"chunk_id":"x","x_hermes_function_offsets":{}}')
    ),
    'mapping.txt.bin': writeSymbolData(SymbolDataType.ProguardMapping, Buffer.from(SMALL_MAPPING)),
    'libbadge.bin': writeSymbolData(
        SymbolDataType.ElfDebugInfo,
        zip({
            dwarf: 'elf bytes',
            '__source/manifest.json': '{}',
            '__source/badge.c': 'int badge;\n',
            '__source/../escape.c': 'nope',
        })
    ),
    'Shop.dSYM': writeSymbolData(
        SymbolDataType.AppleDsym,
        zip({ dwarf: 'mach-o bytes', '__source/main.c': 'int main;\n' })
    ),
    'legacy.bin': v1(SymbolDataType.ProguardMapping, SMALL_MAPPING),
    'unknown-type.bin': writeSymbolData(9 as SymbolDataType, Buffer.from('?')),
    'bad-magic.bin': Buffer.from('not a symbol set at all'),
    'short.bin': Buffer.from('posthog'),
}
