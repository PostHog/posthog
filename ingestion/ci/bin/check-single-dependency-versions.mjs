// Fails when the ingestion packages and the workspace packages they load resolve one runtime dependency to
// different versions. Objects cross these package boundaries (a luxon DateTime, a prom-client registry, an
// OpenTelemetry tracer), and two copies of a library break instanceof checks and shared state.
import { execFileSync } from 'node:child_process'

const packages = JSON.parse(
    execFileSync(
        'pnpm',
        ['list', '--json', '--depth', '0', '--filter', '@posthog/ingestion...', '--filter', '@posthog/ingestion-ai-research...'],
        { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }
    )
)

const versions = new Map()
for (const pkg of packages) {
    for (const [name, { version }] of Object.entries(pkg.dependencies ?? {})) {
        if (version.startsWith('link:') || version.startsWith('file:')) {
            continue
        }
        if (!versions.has(name)) {
            versions.set(name, new Map())
        }
        versions.get(name).set(pkg.name, version)
    }
}

const splits = [...versions].filter(([, byPackage]) => new Set(byPackage.values()).size > 1)
for (const [name, byPackage] of splits) {
    console.error(`${name} resolves to more than one version:`)
    for (const [pkg, version] of byPackage) {
        console.error(`  ${pkg}: ${version}`)
    }
}
if (splits.length > 0) {
    console.error('Align the ranges, or the lockfile entries, so every package gets one copy.')
    process.exit(1)
}
console.log(`${versions.size} shared runtime dependencies, each at one version`)
