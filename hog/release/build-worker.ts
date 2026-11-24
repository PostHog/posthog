// One Linux machine builds hog-worker for every target: Zig's linker carries the macOS and Linux C
// libraries, and cargo-xwin downloads the Windows ones. Run it through release/build-worker.sh,
// whose image holds those tools.

import { copyFile, mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import { parseArgs } from 'node:util'

import { rustTarget, type Target, workerName } from '../src/updates/targets'
import { BUILD_OPTIONS, buildTargets, HOG_ROOT, RELEASE_FOLDER, run, targetFolder } from './shared'

const WORKER_ROOT = join(HOG_ROOT, 'worker')

// The glibc version the Linux builds link against, which Zig takes from the triple. Bun's Linux
// builds reference no newer glibc symbol, so the worker runs wherever hog does.
const GLIBC_FLOOR = '2.17'

// Zig's linker leaves a scratch object file in the folder it runs in, so cargo runs in the target
// folder, which git ignores.
const targetDir = join(WORKER_ROOT, 'target/cross')
const manifest = join(WORKER_ROOT, 'Cargo.toml')

const { version, target } = parseArgs({ options: BUILD_OPTIONS }).values
const targets = buildTargets(target, version)

function buildCommand(target: Target): string[] {
    const triple = rustTarget(target)
    if (target.os === 'win32') {
        return ['cargo', 'xwin', 'build', '--target', triple]
    }
    return ['cargo', 'zigbuild', '--target', target.libc === 'glibc' ? `${triple}.${GLIBC_FLOOR}` : triple]
}

await mkdir(targetDir, { recursive: true })
await run(['rustup', 'target', 'add', ...targets.map(rustTarget)], targetDir)

for (const target of targets) {
    const folder = targetFolder(RELEASE_FOLDER, target)
    const name = workerName(target.os)
    const started = performance.now()

    console.info(`Building hog-worker for ${target.id} (${rustTarget(target)})`)
    await run(
        [...buildCommand(target), '--release', '--locked', '--manifest-path', manifest, '--target-dir', targetDir],
        targetDir,
        {
            ...(version === undefined ? {} : { HOG_RELEASE_VERSION: version }),
            // Accepts the license of Microsoft's C runtime and Windows SDK, which cargo-xwin downloads.
            XWIN_ACCEPT_LICENSE: '1',
        }
    )

    await mkdir(folder, { recursive: true })
    await copyFile(join(targetDir, rustTarget(target), 'release', name), join(folder, name))
    const size = Bun.file(join(folder, name)).size
    console.info(`Built ${join(folder, name)}: ${size} bytes in ${Math.round((performance.now() - started) / 1000)} s`)
}
