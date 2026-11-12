// Prints whether this version may move latest, so a rerun of an older release never moves it back.

import { parseArgs } from 'node:util'

import { manifestUrl } from '../src/updates/release-urls'
import { compareVersions, parseVersion } from '../src/updates/version'

const { values } = parseArgs({ options: { version: { type: 'string' }, 'manifest-url': { type: 'string' } } })
const version = values.version && parseVersion(values.version)
if (!version) {
    console.error('Pass the release version with --version.')
    process.exit(1)
}

const url = values['manifest-url'] ?? manifestUrl({ env: process.env })
const response = await fetch(url, { signal: AbortSignal.timeout(30_000) })
if (response.status === 403 || response.status === 404) {
    process.stdout.write('true\n')
    process.exit(0)
}
if (!response.ok) {
    console.error(`${url} answered with HTTP ${response.status}.`)
    process.exit(1)
}

const current = parseVersion(((await response.json()) as { version?: string }).version ?? '')
process.stdout.write(`${String(!current || compareVersions(version, current) >= 0)}\n`)
