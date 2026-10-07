#!/usr/bin/env node

import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, join } from 'node:path'
import { fileURLToPath } from 'node:url'

// Remove this release-time patch when cargo-dist extends https://github.com/axodotdev/cargo-dist/pull/2311 to its npm installer.
const DOWNLOAD_MAX_ATTEMPTS = 4
const DOWNLOAD_RETRY_BASE_DELAY_MS = 1000

export function isTransientDownloadError(error) {
    const status = Number(/HTTP (\d{3})/.exec(error?.message ?? '')?.[1])
    if (status) {
        return status === 408 || status === 429 || status >= 500
    }

    return (
        ['ECONNRESET', 'ECONNREFUSED', 'EHOSTUNREACH', 'ENETUNREACH', 'ETIMEDOUT', 'EAI_AGAIN'].includes(error?.code) ||
        /socket hang up|network|timed? ?out/i.test(error?.message ?? '')
    )
}

function sleep(delayMs) {
    return new Promise((resolve) => setTimeout(resolve, delayMs))
}

export async function downloadWithRetry(
    operation,
    {
        maxAttempts = DOWNLOAD_MAX_ATTEMPTS,
        baseDelayMs = DOWNLOAD_RETRY_BASE_DELAY_MS,
        sleepFn = sleep,
        onRetry = () => {},
    } = {}
) {
    for (let attempt = 1; ; attempt++) {
        try {
            return await operation()
        } catch (error) {
            if (attempt >= maxAttempts || !isTransientDownloadError(error)) {
                throw error
            }

            const delayMs = baseDelayMs * 2 ** (attempt - 1)
            onRetry(error, attempt, delayMs)
            await sleepFn(delayMs)
        }
    }
}

const RETRY_HELPER_SOURCE = `
const DOWNLOAD_MAX_ATTEMPTS = ${DOWNLOAD_MAX_ATTEMPTS};
const DOWNLOAD_RETRY_BASE_DELAY_MS = ${DOWNLOAD_RETRY_BASE_DELAY_MS};

${isTransientDownloadError.toString()}

${sleep.toString()}

${downloadWithRetry.toString()}
`

// Windows PowerShell joins every argument after -Command into one script, so a positional path
// that contains a space splits in two. The env passes each path to Expand-Archive as one value.
const WINDOWS_EXPAND_ARCHIVE_ANCHOR =
    /`& \{\s*param\(\[string\]\$LiteralPath, \[string\]\$DestinationPath\)\s*Expand-Archive -LiteralPath \$LiteralPath -DestinationPath \$DestinationPath -Force\s*\}`,\s*tempFile,\s*this\.installDirectory,\s*\]\);/
const WINDOWS_EXPAND_ARCHIVE_SOURCE = `"$ErrorActionPreference = 'Stop'; Expand-Archive -LiteralPath $env:POSTHOG_CLI_ZIP -DestinationPath $env:POSTHOG_CLI_DEST -Force",
                  ], {
                    env: {
                      ...process.env,
                      POSTHOG_CLI_ZIP: tempFile,
                      POSTHOG_CLI_DEST: this.installDirectory,
                    },
                  });`

const INSTALLED_ANCHOR =
    /\.then\(\(\) => \{(\s*)if \(!suppressLogs\) \{\s*console\.error\(`\$\{this\.name\} has been installed!`\);/
const INSTALLED_CHECK_SOURCE = `if (!this.exists()) {
          throw new Error(
            \`The archive extracted, but \${this.name} is missing from \${this.installDirectory}\`,
          );
        }`

export function patchBinaryInstaller(source) {
    const importAnchor = 'const http = require("node:http");'
    const downloadAnchor = 'return download(this.url)'

    if (!source.includes(importAnchor)) {
        throw new Error(`Could not find the HTTP import in cargo-dist's binary-install.js`)
    }
    if (!source.includes(downloadAnchor)) {
        throw new Error(`Could not find the artifact download call in cargo-dist's binary-install.js`)
    }
    if (!WINDOWS_EXPAND_ARCHIVE_ANCHOR.test(source)) {
        throw new Error(`Could not find the Windows Expand-Archive call in cargo-dist's binary-install.js`)
    }
    if (!INSTALLED_ANCHOR.test(source)) {
        throw new Error(`Could not find the install success log in cargo-dist's binary-install.js`)
    }
    if (source.includes('downloadWithRetry(() => download(this.url)')) {
        throw new Error(`cargo-dist's binary-install.js is already patched`)
    }

    return source
        .replace(importAnchor, `${importAnchor}\n${RETRY_HELPER_SOURCE}`)
        .replace(WINDOWS_EXPAND_ARCHIVE_ANCHOR, () => WINDOWS_EXPAND_ARCHIVE_SOURCE)
        .replace(
            INSTALLED_ANCHOR,
            (match, indent) => `.then(() => {${indent}${INSTALLED_CHECK_SOURCE}${match.slice('.then(() => {'.length)}`
        )
        .replace(
            downloadAnchor,
            `return downloadWithRetry(() => download(this.url), {\n      onRetry: (error, attempt, delayMs) => {\n        console.error(\n          \`Download attempt \${attempt} failed (\${error.message}); retrying in \${delayMs}ms...\`,\n        );\n      },\n    })`
        )
}

function sha256(path) {
    return createHash('sha256').update(readFileSync(path)).digest('hex')
}

export function patchNpmArchive(archivePath) {
    const workingDirectory = mkdtempSync(join(tmpdir(), 'posthog-cli-npm-'))

    try {
        execFileSync('tar', ['-xzf', archivePath, '-C', workingDirectory])
        const installerPath = join(workingDirectory, 'package', 'binary-install.js')
        writeFileSync(installerPath, patchBinaryInstaller(readFileSync(installerPath, 'utf8')))
        execFileSync('tar', ['-czf', archivePath, '-C', workingDirectory, 'package'])
    } finally {
        rmSync(workingDirectory, { recursive: true, force: true })
    }
}

export function updateReleaseChecksums(distributionDirectory, manifestPath, archivePath) {
    const archiveName = basename(archivePath)
    const archiveChecksum = sha256(archivePath)
    const checksumPath = join(distributionDirectory, 'sha256.sum')
    const checksumLines = readFileSync(checksumPath, 'utf8').trimEnd().split('\n')
    const checksumIndex = checksumLines.findIndex((line) => line.endsWith(`*${archiveName}`))

    if (checksumIndex === -1) {
        throw new Error(`Could not find ${archiveName} in ${checksumPath}`)
    }

    checksumLines[checksumIndex] = `${archiveChecksum} *${archiveName}`
    writeFileSync(checksumPath, `${checksumLines.join('\n')}\n`)

    const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
    const artifact = manifest.artifacts?.[archiveName]
    if (!artifact?.checksums?.sha256) {
        throw new Error(`Could not find the ${archiveName} checksum in ${manifestPath}`)
    }

    artifact.checksums.sha256 = archiveChecksum
    writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`)
}

export function patchCliNpmInstaller(distributionDirectory, manifestPath) {
    const archivePath = join(distributionDirectory, 'posthog-cli-npm-package.tar.gz')
    patchNpmArchive(archivePath)
    updateReleaseChecksums(distributionDirectory, manifestPath, archivePath)
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
    const [distributionDirectory = 'target/distrib', manifestPath = 'dist-manifest.json'] = process.argv.slice(2)
    patchCliNpmInstaller(distributionDirectory, manifestPath)
    console.log('Patched the generated posthog-cli npm installer with download retries and safe Windows extraction')
}
