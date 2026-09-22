import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import {
    downloadWithRetry,
    isTransientDownloadError,
    patchBinaryInstaller,
    patchCliNpmInstaller,
} from './patch-cli-npm-installer.mjs'

const GENERATED_INSTALLER = `const http = require("node:http");

class Package {
  install() {
    return download(this.url)
      .then(() => {});
  }
}
`

test('classifies only transient download failures as retryable', () => {
    for (const message of ['HTTP 408 from URL', 'HTTP 429 from URL', 'HTTP 500 from URL', 'socket hang up']) {
        assert.equal(isTransientDownloadError(new Error(message)), true, message)
    }

    const reset = new Error('read ECONNRESET')
    reset.code = 'ECONNRESET'
    assert.equal(isTransientDownloadError(reset), true)
    assert.equal(isTransientDownloadError(new Error('HTTP 404 from URL')), false)
})

test('retries transient failures with exponential backoff', async () => {
    const delays = []
    let attempts = 0

    const result = await downloadWithRetry(
        async () => {
            attempts++
            if (attempts < 4) {
                throw new Error('HTTP 503 from URL')
            }
            return 'downloaded'
        },
        {
            sleepFn: async (delayMs) => delays.push(delayMs),
        }
    )

    assert.equal(result, 'downloaded')
    assert.equal(attempts, 4)
    assert.deepEqual(delays, [1000, 2000, 4000])
})

test('does not retry permanent failures', async () => {
    let attempts = 0

    await assert.rejects(
        downloadWithRetry(async () => {
            attempts++
            throw new Error('HTTP 404 from URL')
        }),
        /HTTP 404/
    )
    assert.equal(attempts, 1)
})

test('patches the cargo-dist download call', () => {
    const patched = patchBinaryInstaller(GENERATED_INSTALLER)

    assert.match(patched, /downloadWithRetry\(\(\) => download\(this\.url\)/)
    assert.match(patched, /DOWNLOAD_MAX_ATTEMPTS = 4/)
    assert.match(patched, /DOWNLOAD_RETRY_BASE_DELAY_MS = 1000/)
})

test('patches the npm archive and refreshes release checksums', () => {
    const root = mkdtempSync(join(tmpdir(), 'posthog-cli-patcher-test-'))

    try {
        const distributionDirectory = join(root, 'target', 'distrib')
        const packageDirectory = join(root, 'package')
        const archivePath = join(distributionDirectory, 'posthog-cli-npm-package.tar.gz')
        const checksumPath = join(distributionDirectory, 'sha256.sum')
        const manifestPath = join(root, 'dist-manifest.json')
        mkdirSync(distributionDirectory, { recursive: true })
        mkdirSync(packageDirectory)
        writeFileSync(join(packageDirectory, 'binary-install.js'), GENERATED_INSTALLER)
        execFileSync('tar', ['-czf', archivePath, '-C', root, 'package'])
        writeFileSync(checksumPath, `old-checksum *posthog-cli-npm-package.tar.gz\n`)
        writeFileSync(
            manifestPath,
            JSON.stringify({
                artifacts: {
                    'posthog-cli-npm-package.tar.gz': {
                        checksums: { sha256: 'old-checksum' },
                    },
                },
            })
        )

        patchCliNpmInstaller(distributionDirectory, manifestPath)

        const unpackDirectory = join(root, 'unpacked')
        mkdirSync(unpackDirectory)
        execFileSync('tar', ['-xzf', archivePath, '-C', unpackDirectory])
        assert.match(
            readFileSync(join(unpackDirectory, 'package', 'binary-install.js'), 'utf8'),
            /downloadWithRetry\(\(\) => download\(this\.url\)/
        )

        const checksum = createHash('sha256').update(readFileSync(archivePath)).digest('hex')
        assert.equal(readFileSync(checksumPath, 'utf8'), `${checksum} *posthog-cli-npm-package.tar.gz\n`)
        assert.equal(
            JSON.parse(readFileSync(manifestPath, 'utf8')).artifacts['posthog-cli-npm-package.tar.gz'].checksums.sha256,
            checksum
        )
    } finally {
        rmSync(root, { recursive: true, force: true })
    }
})
