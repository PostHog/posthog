import { sourceAndMapPayload, SymbolDataType, writeSymbolData } from '@/error-tracking/container'
import { ZipWriter } from '@/error-tracking/native/zip'

import { SMALL_MAPPING } from './fixtures'

// Stored symbol sets for the extract and download scenarios. hog's writers build them: the upload
// scenarios prove those bytes match posthog-cli's, and here both CLIs only read them.

const zip = (entries: Record<string, string>): Buffer => {
    const writer = new ZipWriter()
    for (const [name, contents] of Object.entries(entries)) {
        writer.add(name, Buffer.from(contents))
    }
    return writer.finish()
}

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
