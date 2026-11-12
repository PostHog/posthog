#!/usr/bin/env node
// Runs the binary from the platform package the package manager picked from optionalDependencies.
'use strict'

const { spawnSync } = require('node:child_process')
const path = require('node:path')

// npm's own test for the `libc` of optional dependencies, so the launcher finds the package npm installed.
function libcFamily(report) {
    if (report?.header?.glibcVersionRuntime) {
        return 'glibc'
    }
    const objects = Array.isArray(report?.sharedObjects) ? report.sharedObjects : []
    return objects.some((file) => file.includes('libc.musl-') || file.includes('ld-musl-')) ? 'musl' : undefined
}

function processReport() {
    try {
        const exclude = process.report.excludeNetwork
        process.report.excludeNetwork = true
        const report = process.report.getReport()
        process.report.excludeNetwork = exclude
        return report
    } catch {
        return undefined
    }
}

function targetId(platform, arch, musl) {
    const cpu = { x64: 'x64', arm64: 'arm64' }[arch]
    if (!cpu) {
        return undefined
    }
    if (platform === 'darwin') {
        return `darwin-${cpu}`
    }
    if (platform === 'linux') {
        return musl ? `linux-${cpu}-musl` : `linux-${cpu}`
    }
    if (platform === 'win32') {
        return `windows-${cpu}`
    }
    return undefined
}

function fail(message) {
    process.stderr.write(`hog: ${message}\n`)
    process.exit(1)
}

function candidates(platform, arch, libc) {
    const first = targetId(platform, arch, libc === 'musl')
    const second = platform === 'linux' ? targetId(platform, arch, libc !== 'musl') : undefined
    return [first, second].filter(Boolean)
}

function main() {
    const libc = process.platform === 'linux' ? libcFamily(processReport()) : undefined
    const targets = candidates(process.platform, process.arch, libc)
    if (targets.length === 0) {
        fail(
            `there is no hog build for ${process.platform} on ${process.arch}. ` +
                'See https://github.com/PostHog/posthog/tree/master/hog for the supported platforms.'
        )
    }

    const packageName = `@posthog/hog-${targets[0]}`
    let binary
    for (const target of targets) {
        try {
            const packageJson = require.resolve(`@posthog/hog-${target}/package.json`)
            binary = path.join(path.dirname(packageJson), 'bin', process.platform === 'win32' ? 'hog.exe' : 'hog')
            break
        } catch {}
    }
    if (!binary) {
        fail(
            `the package ${packageName}, which holds the hog binary for this machine, isn't installed. ` +
                'Your package manager may have skipped optional dependencies. Reinstall @posthog/hog without ' +
                '--no-optional or --omit=optional.'
        )
    }

    const result = spawnSync(binary, process.argv.slice(2), { stdio: 'inherit' })
    if (result.error) {
        fail(`couldn't start ${binary}: ${result.error.message}`)
    }

    if (result.signal) {
        process.kill(process.pid, result.signal)
        return
    }
    process.exit(result.status ?? 1)
}

if (require.main === module) {
    main()
} else {
    module.exports = { candidates, libcFamily, targetId }
}
