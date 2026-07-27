import { mkdirSync, readFileSync, writeFileSync } from 'fs'
import { join } from 'path'
import { brotliDecompressSync } from 'zlib'

// Jest's CLI only sets NODE_ENV=test when it is unset. When tests are launched
// from an environment where NODE_ENV or DEBUG is already set (IDE test runners,
// debuggers, flox exports DEBUG=1), `determineNodeEnv()` resolves to dev and
// every config default (DATABASE_URL, PERSONS_DATABASE_URL, CLICKHOUSE_DATABASE,
// CYCLOTRON_DATABASE_URL, ...) points at the real dev databases — which
// destructive test helpers would then wipe. Force the test environment so the
// defaults always resolve to their test_* counterparts. Explicitly exported
// *_DATABASE_URL variables still win; tests/helpers/database-guard.ts catches
// those when they point at a non-test database.
process.env.NODE_ENV = 'test'

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
