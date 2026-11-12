#!/usr/bin/env node
// Runs the binary from the platform package the package manager picked from optionalDependencies.
'use strict'

const { spawnSync } = require('node:child_process')
const { readdirSync } = require('node:fs')
const path = require('node:path')

// Only musl systems, such as Alpine, have an ld-musl-<arch>.so.1 loader. install.sh checks the same.
function isMusl(readdir) {
    for (const folder of ['/lib', '/usr/lib']) {
        try {
            if (readdir(folder).some((name) => name.startsWith('ld-musl-'))) {
                return true
            }
        } catch {}
    }
    return false
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

function main() {
    const target = targetId(process.platform, process.arch, process.platform === 'linux' && isMusl(readdirSync))
    if (!target) {
        fail(
            `there is no hog build for ${process.platform} on ${process.arch}. ` +
                'See https://github.com/PostHog/posthog/tree/master/hog for the supported platforms.'
        )
    }

    const packageName = `@posthog/hog-${target}`
    let binary
    try {
        const packageJson = require.resolve(`${packageName}/package.json`)
        binary = path.join(path.dirname(packageJson), 'bin', process.platform === 'win32' ? 'hog.exe' : 'hog')
    } catch {
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
    module.exports = { isMusl, targetId }
}
