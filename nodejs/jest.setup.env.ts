import { mkdirSync, readFileSync, writeFileSync } from 'fs'
import { join } from 'path'
import { brotliDecompressSync } from 'zlib'

// Tests must never read the live GeoLite2 database from share/ — it is re-downloaded
// unpinned from mmdbcdn.posthog.net and its data changes under us (see the recurring
// postal-code snapshot drift). Point every GeoIPService at MaxMind's frozen test
// database instead, so lookups are deterministic. Use IPs from the test ranges
// (e.g. 89.160.20.129 → Linköping, 216.160.83.56 → Milton) in tests.
const fixturePath = join(__dirname, 'tests', 'assets', 'GeoLite2-City-Test.mmdb.br')
const mmdbPath = join(__dirname, '.tmp', 'GeoLite2-City-Test.mmdb')

mkdirSync(join(__dirname, '.tmp'), { recursive: true })
writeFileSync(mmdbPath, brotliDecompressSync(readFileSync(fixturePath)))
// Sidecar metadata file, so GeoIPService doesn't warn about a missing one on every load
writeFileSync(mmdbPath.replace('.mmdb', '.json'), JSON.stringify({ date: '2025-01-01' }))

process.env.MMDB_FILE_LOCATION = mmdbPath
