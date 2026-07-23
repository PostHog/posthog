/* eslint-disable no-console */
/**
 * Local benchmark: legacy TS geoip plugin vs the geoip Hog template on the Node VM and the
 * Rust VM (@posthog/hogvm-node).
 *
 * Run from nodejs/: npx tsx src/dev/bench-geoip.ts
 * Requires: rust/common/hogvm/node built (pnpm run build there) and share/GeoLite2-City.mmdb.
 */
import { Reader } from '@maxmind/geoip2-node'
import { readFileSync } from 'fs'
import path from 'path'

import { DEFAULT_TIMEOUT_MS, exec } from '@posthog/hogvm'

import { getTransformationFunctions } from '../cdp/hog-transformations/transformation-functions'
import { processEvent } from '../cdp/legacy-plugins/_transformations/posthog-plugin-geoip'
import { template } from '../cdp/templates/_transformations/geoip/geoip.template'
import { compileHog } from '../cdp/templates/compiler'

const MMDB_PATH = path.resolve(__dirname, '../../../share/GeoLite2-City.mmdb')
const ITERS = Number(process.env.BENCH_ITERS || 20_000)
const WARMUP = Number(process.env.BENCH_WARMUP || 2_000)

const IPS = ['89.160.20.129', '13.106.122.3', '208.80.154.224', '2.16.0.1', '186.192.90.5']

function makeEvent(i: number, padBytes = 0): any {
    const properties: Record<string, any> = {
        $ip: IPS[i % IPS.length],
        $current_url: 'https://app.example.com/dashboard/123?utm_source=news',
        $pathname: '/dashboard/123',
        $browser: 'Chrome',
        $browser_version: 126,
        $os: 'Mac OS X',
        $device_type: 'Desktop',
        $screen_height: 1080,
        $screen_width: 1920,
        $viewport_height: 975,
        $viewport_width: 1920,
        $lib: 'web',
        $lib_version: '1.150.0',
        $session_id: '01900000-0000-7000-8000-000000000000',
        $window_id: '01900000-0000-7000-8000-000000000001',
        $referrer: 'https://www.google.com/',
        $referring_domain: 'www.google.com',
        distinct_id: `user-${i % 1000}`,
        token: 'phc_abcdefghijklmnopqrstuvwxyz123456',
        $active_feature_flags: ['flag-a', 'flag-b', 'flag-c'],
        $feature_flag_payloads: { 'flag-a': { variant: 'test' } },
        $set: { email: 'user@example.com', plan: 'scale' },
        $set_once: { first_seen: '2024-01-01' },
        custom_prop_1: 'value-1',
        custom_prop_2: 42,
        custom_prop_3: true,
        custom_prop_4: ['a', 'b', 'c'],
        custom_prop_5: { nested: { deep: 'value' } },
    }
    if (padBytes > 0) {
        properties.$big_blob = 'x'.repeat(padBytes)
    }
    return {
        uuid: '01900000-0000-7000-8000-00000000abcd',
        event: '$pageview',
        distinct_id: `user-${i % 1000}`,
        team_id: 2,
        timestamp: '2026-07-23T10:00:00.000Z',
        properties,
    }
}

function buildGlobals(event: any): any {
    return {
        project: { id: event.team_id, name: '', url: 'http://localhost:8000' },
        event: {
            uuid: event.uuid,
            event: event.event,
            distinct_id: event.distinct_id,
            properties: event.properties || {},
            elements_chain: event.properties?.$elements_chain || '',
            timestamp: event.timestamp || '',
            url: event.properties?.$current_url || '',
        },
        inputs: {},
    }
}

// Same output as the stock geoip template, but: no runtime f-string keys outside the (rare)
// subdivisions loop, no dead `if (value != null)` branch, defaults written from literal maps.
const SLIMMED_TEMPLATE_CODE = `
if (event.properties?.$geoip_disable or empty(event.properties?.$ip)) {
    print('geoip disabled or no ip.')
    return event
}
let ip := event.properties.$ip
if (ip == '127.0.0.1' or substring(ip, 1, 8) == '192.168.') {
    print('spoofing ip for local development', ip)
    ip := '89.160.20.129'
}
let response := geoipLookup(ip)
if (not response) {
    print('geoip lookup failed for ip', ip)
    return event
}
let location := {}
let initialLocation := {}
if (response.city) {
    location['$geoip_city_name'] := response.city.names?.en
    initialLocation['$initial_geoip_city_name'] := response.city.names?.en
}
if (response.country) {
    location['$geoip_country_name'] := response.country.names?.en
    location['$geoip_country_code'] := response.country.isoCode
    initialLocation['$initial_geoip_country_name'] := response.country.names?.en
    initialLocation['$initial_geoip_country_code'] := response.country.isoCode
}
if (response.continent) {
    location['$geoip_continent_name'] := response.continent.names?.en
    location['$geoip_continent_code'] := response.continent.code
    initialLocation['$initial_geoip_continent_name'] := response.continent.names?.en
    initialLocation['$initial_geoip_continent_code'] := response.continent.code
}
if (response.postal) {
    location['$geoip_postal_code'] := response.postal.code
    initialLocation['$initial_geoip_postal_code'] := response.postal.code
}
if (response.location) {
    location['$geoip_latitude'] := response.location?.latitude
    location['$geoip_longitude'] := response.location?.longitude
    location['$geoip_accuracy_radius'] := response.location?.accuracyRadius
    location['$geoip_time_zone'] := response.location?.timeZone
    initialLocation['$initial_geoip_latitude'] := response.location?.latitude
    initialLocation['$initial_geoip_longitude'] := response.location?.longitude
    initialLocation['$initial_geoip_accuracy_radius'] := response.location?.accuracyRadius
    initialLocation['$initial_geoip_time_zone'] := response.location?.timeZone
}
if (response.subdivisions) {
    for (let index, subdivision in response.subdivisions) {
        location[f'$geoip_subdivision_{index + 1}_code'] := subdivision.isoCode
        location[f'$geoip_subdivision_{index + 1}_name'] := subdivision.names?.en
        initialLocation[f'$initial_geoip_subdivision_{index + 1}_code'] := subdivision.isoCode
        initialLocation[f'$initial_geoip_subdivision_{index + 1}_name'] := subdivision.names?.en
    }
}
print('geoip location data for ip:', location)
let returnEvent := event
returnEvent.properties := returnEvent.properties ?? {}
returnEvent.properties.$set := returnEvent.properties.$set ?? {}
returnEvent.properties.$set_once := returnEvent.properties.$set_once ?? {}
let setDefaults := {
    '$geoip_city_name': null,
    '$geoip_city_confidence': null,
    '$geoip_subdivision_2_name': null,
    '$geoip_subdivision_2_code': null,
    '$geoip_subdivision_1_name': null,
    '$geoip_subdivision_1_code': null,
    '$geoip_country_name': null,
    '$geoip_country_code': null,
    '$geoip_continent_name': null,
    '$geoip_continent_code': null,
    '$geoip_postal_code': null,
    '$geoip_latitude': null,
    '$geoip_longitude': null,
    '$geoip_accuracy_radius': null,
    '$geoip_time_zone': null
}
let setOnceDefaults := {
    '$initial_geoip_city_name': null,
    '$initial_geoip_city_confidence': null,
    '$initial_geoip_subdivision_2_name': null,
    '$initial_geoip_subdivision_2_code': null,
    '$initial_geoip_subdivision_1_name': null,
    '$initial_geoip_subdivision_1_code': null,
    '$initial_geoip_country_name': null,
    '$initial_geoip_country_code': null,
    '$initial_geoip_continent_name': null,
    '$initial_geoip_continent_code': null,
    '$initial_geoip_postal_code': null,
    '$initial_geoip_latitude': null,
    '$initial_geoip_longitude': null,
    '$initial_geoip_accuracy_radius': null,
    '$initial_geoip_time_zone': null
}
for (let key, value in setDefaults) {
    returnEvent.properties.$set[key] := value
}
for (let key, value in setOnceDefaults) {
    returnEvent.properties.$set_once[key] := value
}
for (let key, value in location) {
    returnEvent.properties[key] := value
    returnEvent.properties.$set[key] := value
}
for (let key, value in initialLocation) {
    returnEvent.properties.$set_once[key] := value
}
return returnEvent
`

function sortedJson(value: any): string {
    return JSON.stringify(value, (_k, v) =>
        v && typeof v === 'object' && !Array.isArray(v) ? Object.fromEntries(Object.entries(v).sort()) : v
    )
}

interface BenchResult {
    name: string
    usPerOp: number
    extra?: string
}

function bench(name: string, fn: (i: number) => void, extra?: () => string): BenchResult {
    for (let i = 0; i < WARMUP; i++) {
        fn(i)
    }
    ;(globalThis as { gc?: () => void }).gc?.()
    const start = process.hrtime.bigint()
    for (let i = 0; i < ITERS; i++) {
        fn(i)
    }
    const totalNs = Number(process.hrtime.bigint() - start)
    return { name, usPerOp: totalNs / 1000 / ITERS, extra: extra?.() }
}

async function main(): Promise<void> {
    console.log(`iters=${ITERS} warmup=${WARMUP} mmdb=${MMDB_PATH}`)

    // --- Setup: legacy plugin ---
    const reader = Reader.openBuffer(readFileSync(MMDB_PATH))
    const geoIp = {
        city: (ip: string) => {
            try {
                return reader.city(ip)
            } catch {
                return null
            }
        },
    }
    const legacyMeta: any = { geoip: { locate: (ip: string) => geoIp.city(ip) }, logger: console }

    // --- Setup: hog template bytecode + node VM functions ---
    const bytecode = await compileHog(template.code)
    console.log(`geoip template bytecode: ${bytecode.length} tokens`)
    const trivialBytecode = await compileHog('return event')
    const lookupOnlyBytecode = await compileHog(`let r := geoipLookup(event.properties.$ip)\nreturn r.country.isoCode`)
    const noPrintCode = template.code
        .split('\n')
        .filter((l) => !l.trim().startsWith('print('))
        .join('\n')
    const noPrintBytecode = await compileHog(noPrintCode)
    const slimmedBytecode = await compileHog(SLIMMED_TEMPLATE_CODE)
    // Production captures print() into result logs; the default exec print hits the console.
    // A sink keeps the console quiet while still paying the call overhead.
    const printSink: string[] = []
    const nodeVmFunctions = {
        ...getTransformationFunctions(geoIp),
        print: (...args: any[]) => {
            printSink.length = 0
            printSink.push(args.map(String).join(', '))
        },
    }

    // --- Setup: rust VM ---
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const rustVm = require('@posthog/hogvm-node')
    rustVm.init({ mmdbPath: MMDB_PATH, knownBotUaList: ['googlebot'], knownBotIpList: ['1.2.3.4'] })
    const sanity = rustVm.executeSync(bytecode, buildGlobals(makeEvent(0)), { maxSteps: 1_000_000 })
    if (sanity.error) {
        throw new Error(`rust sanity check failed: ${sanity.error}`)
    }
    const nodeSanity = exec(bytecode, {
        globals: buildGlobals(makeEvent(0)),
        timeout: DEFAULT_TIMEOUT_MS,
        maxAsyncSteps: 0,
        functions: nodeVmFunctions,
    })
    if (nodeSanity.error) {
        throw new Error(`node vm sanity check failed: ${nodeSanity.error}`)
    }
    const legacySanity = processEvent(makeEvent(0), legacyMeta)
    if (!legacySanity.properties.$geoip_country_code) {
        throw new Error('legacy sanity check failed: no $geoip_country_code')
    }
    console.log('sanity checks passed\n')

    // Parity: slimmed template must produce the same event as the stock template (key order aside)
    for (let i = 0; i < IPS.length * 2; i++) {
        const original = rustVm.executeSync(bytecode, buildGlobals(makeEvent(i)), { maxSteps: 1_000_000 })
        const slimmed = rustVm.executeSync(slimmedBytecode, buildGlobals(makeEvent(i)), { maxSteps: 1_000_000 })
        if (original.error || slimmed.error) {
            throw new Error(`parity run error: ${original.error || slimmed.error}`)
        }
        if (sortedJson(original.result) !== sortedJson(slimmed.result)) {
            console.error('original:', JSON.stringify(original.result, null, 2))
            console.error('slimmed:', JSON.stringify(slimmed.result, null, 2))
            throw new Error(`slimmed template output diverges for event ${i}`)
        }
    }
    console.log('slimmed template parity check passed\n')

    // Dump inputs for the pure-rust profiling harness
    if (process.env.BENCH_DUMP_DIR) {
        const { writeFileSync } = await import('fs')
        writeFileSync(path.join(process.env.BENCH_DUMP_DIR, 'geoip-bytecode.json'), JSON.stringify(bytecode))
        writeFileSync(
            path.join(process.env.BENCH_DUMP_DIR, 'geoip-bytecode-slimmed.json'),
            JSON.stringify(slimmedBytecode)
        )
        writeFileSync(
            path.join(process.env.BENCH_DUMP_DIR, 'geoip-globals.json'),
            JSON.stringify([0, 1, 2, 3, 4].map((i) => buildGlobals(makeEvent(i))))
        )
        console.log(`dumped bytecode + globals to ${process.env.BENCH_DUMP_DIR}\n`)
    }

    const scenarios: [string, number][] = [
        ['small event (~2KB props)', 0],
        ['large event (+64KB blob prop)', 64 * 1024],
    ]

    for (const [label, pad] of scenarios) {
        console.log(`=== ${label} ===`)
        const results: BenchResult[] = []

        // Pre-build event pools so per-iteration clone cost is out of the measured loop.
        // Legacy mutates the event in place, so it needs a fresh one per iteration.
        const POOL = 2_000
        const legacyPool: any[] = []
        const globalsPool: any[] = []
        for (let i = 0; i < POOL; i++) {
            globalsPool.push(buildGlobals(makeEvent(i, pad)))
        }
        const refillLegacyPool = (): void => {
            legacyPool.length = 0
            for (let i = 0; i < POOL; i++) {
                legacyPool.push(makeEvent(i, pad))
            }
        }

        // Baseline: event construction only (what refills cost if inlined)
        results.push(bench('baseline: makeEvent only', (i) => void makeEvent(i, pad)))

        // Legacy plugin: fresh events, refilling the pool outside timing is impossible inside
        // bench(), so include makeEvent and subtract the baseline mentally.
        results.push(bench('legacy plugin (incl. makeEvent)', (i) => void processEvent(makeEvent(i, pad), legacyMeta)))

        // Node VM
        results.push(
            bench('node hogvm (template)', (i) => {
                const r = exec(bytecode, {
                    globals: globalsPool[i % POOL],
                    timeout: DEFAULT_TIMEOUT_MS,
                    maxAsyncSteps: 0,
                    functions: nodeVmFunctions,
                })
                if (r.error) {
                    throw new Error(String(r.error))
                }
            })
        )

        // Rust VM — track internal duration to split marshalling from execution
        let rustInternalUs = 0
        let rustCalls = 0
        results.push(
            bench(
                'rust hogvm (template)',
                (i) => {
                    const r = rustVm.executeSync(bytecode, globalsPool[i % POOL], { maxSteps: 1_000_000 })
                    if (r.error) {
                        throw new Error(r.error)
                    }
                    rustInternalUs += r.durationUs
                    rustCalls++
                },
                () => `internal exec avg ${(rustInternalUs / rustCalls).toFixed(1)}us`
            )
        )

        // Rust VM: lookup + record construction only
        let lookupInternalUs = 0
        let lookupCalls = 0
        results.push(
            bench(
                'rust hogvm (geoipLookup only)',
                (i) => {
                    const r = rustVm.executeSync(lookupOnlyBytecode, globalsPool[i % POOL], { maxSteps: 1_000_000 })
                    if (r.error) {
                        throw new Error(r.error)
                    }
                    lookupInternalUs += r.durationUs
                    lookupCalls++
                },
                () => `internal exec avg ${(lookupInternalUs / lookupCalls).toFixed(1)}us`
            )
        )

        // Rust VM: full template minus print statements
        let noPrintInternalUs = 0
        let noPrintCalls = 0
        results.push(
            bench(
                'rust hogvm (template, no print)',
                (i) => {
                    const r = rustVm.executeSync(noPrintBytecode, globalsPool[i % POOL], { maxSteps: 1_000_000 })
                    if (r.error) {
                        throw new Error(r.error)
                    }
                    noPrintInternalUs += r.durationUs
                    noPrintCalls++
                },
                () => `internal exec avg ${(noPrintInternalUs / noPrintCalls).toFixed(1)}us`
            )
        )

        // Rust VM: full template on a $geoip_disable event — early return, isolates per-call
        // fixed overhead (bytecode marshal + Program::new parse) for the big program
        const disabledGlobals = globalsPool.map((g) => ({
            ...g,
            event: { ...g.event, properties: { ...g.event.properties, $geoip_disable: true } },
        }))
        let disabledInternalUs = 0
        let disabledCalls = 0
        results.push(
            bench(
                'rust hogvm (template, disabled)',
                (i) => {
                    const r = rustVm.executeSync(bytecode, disabledGlobals[i % POOL], { maxSteps: 1_000_000 })
                    if (r.error) {
                        throw new Error(r.error)
                    }
                    disabledInternalUs += r.durationUs
                    disabledCalls++
                },
                () => `internal exec avg ${(disabledInternalUs / disabledCalls).toFixed(1)}us`
            )
        )

        // Node VM: template minus print for symmetry
        results.push(
            bench('node hogvm (template, no print)', (i) => {
                const r = exec(noPrintBytecode, {
                    globals: globalsPool[i % POOL],
                    timeout: DEFAULT_TIMEOUT_MS,
                    maxAsyncSteps: 0,
                    functions: nodeVmFunctions,
                })
                if (r.error) {
                    throw new Error(String(r.error))
                }
            })
        )

        // Rust VM: slimmed template (no f-string keys, no dead branch)
        let slimInternalUs = 0
        let slimCalls = 0
        results.push(
            bench(
                'rust hogvm (template, slimmed)',
                (i) => {
                    const r = rustVm.executeSync(slimmedBytecode, globalsPool[i % POOL], { maxSteps: 1_000_000 })
                    if (r.error) {
                        throw new Error(r.error)
                    }
                    slimInternalUs += r.durationUs
                    slimCalls++
                },
                () => `internal exec avg ${(slimInternalUs / slimCalls).toFixed(1)}us`
            )
        )

        // Node VM: slimmed template for symmetry
        results.push(
            bench('node hogvm (template, slimmed)', (i) => {
                const r = exec(slimmedBytecode, {
                    globals: globalsPool[i % POOL],
                    timeout: DEFAULT_TIMEOUT_MS,
                    maxAsyncSteps: 0,
                    functions: nodeVmFunctions,
                })
                if (r.error) {
                    throw new Error(String(r.error))
                }
            })
        )

        // Rust VM: pre-registered program (no per-call bytecode marshal/copy)
        const handle = rustVm.registerProgram(bytecode)
        let cachedInternalUs = 0
        let cachedCalls = 0
        results.push(
            bench(
                'rust hogvm (template, cached prog)',
                (i) => {
                    const r = rustVm.executeRegisteredSync(handle, globalsPool[i % POOL], { maxSteps: 1_000_000 })
                    if (r.error) {
                        throw new Error(r.error)
                    }
                    cachedInternalUs += r.durationUs
                    cachedCalls++
                },
                () => `internal exec avg ${(cachedInternalUs / cachedCalls).toFixed(1)}us`
            )
        )

        // Rust VM: cached program + batched napi crossing (100 events per call)
        const BATCH = 100
        const batches: any[][] = []
        for (let b = 0; b < POOL / BATCH; b++) {
            batches.push(globalsPool.slice(b * BATCH, (b + 1) * BATCH))
        }
        {
            const warmBatches = Math.ceil(WARMUP / BATCH)
            for (let b = 0; b < warmBatches; b++) {
                rustVm.executeRegisteredBatchSync(handle, batches[b % batches.length], { maxSteps: 1_000_000 })
            }
            const nBatches = Math.ceil(ITERS / BATCH)
            const start = process.hrtime.bigint()
            for (let b = 0; b < nBatches; b++) {
                const rs = rustVm.executeRegisteredBatchSync(handle, batches[b % batches.length], {
                    maxSteps: 1_000_000,
                })
                if (rs.some((r: any) => r.error)) {
                    throw new Error('batch error')
                }
            }
            const totalNs = Number(process.hrtime.bigint() - start)
            results.push({
                name: `rust hogvm (cached, batch ${BATCH})`,
                usPerOp: totalNs / 1000 / (nBatches * BATCH),
            })
        }

        // Rust VM with trivial program (return event): isolates globals marshal + result marshal
        let trivialInternalUs = 0
        let trivialCalls = 0
        results.push(
            bench(
                'rust hogvm (return event)',
                (i) => {
                    const r = rustVm.executeSync(trivialBytecode, globalsPool[i % POOL], { maxSteps: 1_000_000 })
                    if (r.error) {
                        throw new Error(r.error)
                    }
                    trivialInternalUs += r.durationUs
                    trivialCalls++
                },
                () => `internal exec avg ${(trivialInternalUs / trivialCalls).toFixed(1)}us`
            )
        )

        // Node VM with trivial program for symmetry
        results.push(
            bench('node hogvm (return event)', (i) => {
                const r = exec(trivialBytecode, {
                    globals: globalsPool[i % POOL],
                    timeout: DEFAULT_TIMEOUT_MS,
                    maxAsyncSteps: 0,
                    functions: nodeVmFunctions,
                })
                if (r.error) {
                    throw new Error(String(r.error))
                }
            })
        )

        refillLegacyPool() // keep pool referenced so it is not optimized away
        void legacyPool

        for (const r of results) {
            console.log(
                `  ${r.name.padEnd(36)} ${r.usPerOp.toFixed(1).padStart(8)} us/op ${r.extra ? `(${r.extra})` : ''}`
            )
        }
        console.log()
    }

    // Raw mmdb lookup comparison, out of both VMs
    console.log('=== raw geoip lookup only ===')
    const r1 = bench('node @maxmind/geoip2-node reader.city', (i) => void geoIp.city(IPS[i % IPS.length]))
    console.log(`  ${r1.name.padEnd(36)} ${r1.usPerOp.toFixed(1).padStart(8)} us/op`)
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
