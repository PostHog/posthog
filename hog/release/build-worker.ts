// Builds hog-worker, the Rust program in worker/, for every target and puts each build next to the
// hog binary release/compile.ts wrote. One Linux machine builds them all: Zig's linker carries the
// macOS and Linux C libraries, and cargo-xwin downloads the Windows ones. Run it through
// release/build-worker.sh, whose image holds those tools.

import { copyFile, mkdir } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { parseArgs } from 'node:util'

import { findTarget, rustTarget, TARGETS, type Target, workerName } from '../src/updates/targets'
import { parseVersion } from '../src/updates/version'

const HOG_ROOT = resolve(import.meta.dir, '..')
const WORKER_ROOT = join(HOG_ROOT, 'worker')

// The glibc version the Linux builds link against, which Zig takes from the triple. Bun's Linux
// builds reference no newer glibc symbol, so the worker runs wherever hog does.
const GLIBC_FLOOR = '2.17'

const { values } = parseArgs({
    options: {
        target: { type: 'string', multiple: true },
        out: { type: 'string', default: join(HOG_ROOT, 'dist/release') },
        'target-dir': { type: 'string', default: join(WORKER_ROOT, 'target/cross') },
        version: { type: 'string' },
    },
})

if (values.version !== undefined && !parseVersion(values.version)) {
    console.error(`--version ${values.version} isn't a semver version.`)
    process.exit(1)
}

const targetDir = resolve(values['target-dir'])
const manifest = join(WORKER_ROOT, 'Cargo.toml')

function buildCommand(target: Target): string[] {
    const triple = rustTarget(target)
    if (target.os === 'win32') {
        return ['cargo', 'xwin', 'build', '--target', triple]
    }
    return ['cargo', 'zigbuild', '--target', target.libc === 'glibc' ? `${triple}.${GLIBC_FLOOR}` : triple]
}

// Zig's linker leaves a scratch object file in the folder it runs in, so cargo runs in the target
// folder, which git ignores.
async function run(command: string[], env: Record<string, string>): Promise<void> {
    const child = Bun.spawn(command, {
        cwd: targetDir,
        env: { ...process.env, ...env },
        stdout: 'inherit',
        stderr: 'inherit',
    })
    if ((await child.exited) !== 0) {
        console.error(`${command.join(' ')} failed.`)
        process.exit(1)
    }
}

const targets = values.target ? values.target.map(findTarget) : TARGETS

await mkdir(targetDir, { recursive: true })
await run(['rustup', 'target', 'add', ...targets.map(rustTarget)], {})

for (const target of targets) {
    const folder = join(resolve(values.out), 'bin', target.id)
    const name = workerName(target.os)
    const started = performance.now()

    console.info(`Building hog-worker for ${target.id} (${rustTarget(target)})`)
    await run(
        [...buildCommand(target), '--release', '--locked', '--manifest-path', manifest, '--target-dir', targetDir],
        {
            ...(values.version === undefined ? {} : { HOG_RELEASE_VERSION: values.version }),
            // Accepts the license of Microsoft's C runtime and Windows SDK, which cargo-xwin downloads.
            XWIN_ACCEPT_LICENSE: '1',
        }
    )

    await mkdir(folder, { recursive: true })
    await copyFile(join(targetDir, rustTarget(target), 'release', name), join(folder, name))
    const size = Bun.file(join(folder, name)).size
    console.info(`Built ${join(folder, name)}: ${size} bytes in ${Math.round((performance.now() - started) / 1000)} s`)
}
