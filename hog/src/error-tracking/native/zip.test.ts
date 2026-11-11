import { describe, expect, test } from 'bun:test'
import { mkdtempSync, readdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { SymbolDataType, writeSymbolData } from '../container'
import { extractSymbolSet } from '../symbols'
import { ZipWriter } from './zip'

describe('ZipWriter', () => {
    test('writes and reads an archive with more entries than a zip without ZIP64 holds', () => {
        const zip = new ZipWriter()
        zip.add('dwarf', Buffer.from('not really dwarf'))
        zip.add('__source/manifest.json', Buffer.from('{}'))
        for (let i = 0; i < 65534; i++) {
            zip.add(`__source/f${i}.c`, Buffer.from(`int f${i};\n`))
        }
        const archive = zip.finish()

        // The zip crate 2.4.2 posthog-cli uses writes these exact bytes for the same entries.
        expect(new Bun.CryptoHasher('sha256').update(archive).digest('hex')).toBe(
            '3d769dba09591dbe4236fc8b22551102700886babca1c94c6ff684bc5beea2f0'
        )
        const folder = mkdtempSync(join(tmpdir(), 'hog-zip64-'))
        extractSymbolSet(writeSymbolData(SymbolDataType.AppleDsym, archive), 'Big', folder, folder)
        expect(readdirSync(join(folder, 'Big/__source')).length).toBe(65535)
    }, 30_000)
})
