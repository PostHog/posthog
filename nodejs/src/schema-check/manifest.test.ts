import { readFileSync } from 'fs'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import { ManifestError, buildManifest, parseManifest } from './manifest'

const EXAMPLES = path.resolve(__dirname, '..', '..', '..', 'tools', 'deploy-requirements', 'examples')

describe('deploy requirements manifest v1', () => {
    it('writes the Node example, digest included', () => {
        const example = parseJSON(readFileSync(path.join(EXAMPLES, 'node.json'), 'utf8'))
        const parsed = parseManifest(JSON.stringify(example))

        expect(buildManifest(parsed.requirements, parsed.source_commit)).toEqual(example)
    })

    it('reads the sqlx requirements and digest of the Rust example', () => {
        const rust = parseJSON(readFileSync(path.join(EXAMPLES, 'rust.json'), 'utf8'))
        // A Node image always needs Django migrations, so the Node parser adds one to read a Rust list.
        const django = { kind: 'django', database: 'default', app: 'posthog', migration: '0001_initial' }
        const manifest = buildManifest([django, ...rust.requirements], null)

        expect(parseManifest(JSON.stringify(manifest)).requirements.slice(1)).toEqual(rust.requirements)
        expect(buildManifest(rust.requirements, null).digest).toEqual(rust.digest)
    })

    it('rejects an unknown schema version', () => {
        const text = readFileSync(path.join(EXAMPLES, 'node.json'), 'utf8').replace(
            '"schema_version": 1',
            '"schema_version": 2'
        )

        expect(() => parseManifest(text)).toThrow(ManifestError)
    })
})
