// Compiles hog for every release target, or for the ones named with --target, into
// dist/release/bin/<target>/. Bun cross-compiles, so one machine builds all of them.
//
//   bun release/compile.ts --version 1.0.0-alpha.4 [--build-date <iso>] [--target darwin-arm64 ...]
//
// --version and --build-date go into the binary, which reports them and compares them with the latest
// release. Without --version the build is a dev build, which never checks for updates.
// Run `pnpm run build:mcp` first: the binary embeds the MCP tool catalog and skills library.

import { existsSync } from 'node:fs'
import { mkdir } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { parseArgs } from 'node:util'

import { binaryName, findTarget, TARGETS } from '../src/upgrade/targets'
import { parseVersion } from '../src/upgrade/version'

const HOG_ROOT = resolve(import.meta.dir, '..')
const MCP_LIBRARY = resolve(HOG_ROOT, '../services/mcp/dist/cli-library.mjs')

const { values } = parseArgs({
    options: {
        target: { type: 'string', multiple: true },
        out: { type: 'string', default: join(HOG_ROOT, 'dist/release') },
        version: { type: 'string' },
        'build-date': { type: 'string' },
    },
})

if (!existsSync(MCP_LIBRARY)) {
    console.error(`Missing ${MCP_LIBRARY}. Run \`pnpm --filter @posthog/hog build:mcp\` first.`)
    process.exit(1)
}

if (values.version !== undefined && !parseVersion(values.version)) {
    console.error(`--version ${values.version} isn't a semver version.`)
    process.exit(1)
}

const buildDate = values['build-date'] ?? new Date().toISOString()
if (Number.isNaN(Date.parse(buildDate))) {
    console.error(`--build-date ${buildDate} isn't a date.`)
    process.exit(1)
}

const defines =
    values.version === undefined
        ? []
        : [
              `--define=HOG_RELEASE_VERSION=${JSON.stringify(values.version)}`,
              `--define=HOG_BUILD_DATE=${JSON.stringify(buildDate)}`,
          ]

const targets = values.target ? values.target.map(findTarget) : TARGETS

for (const target of targets) {
    const folder = join(resolve(values.out), 'bin', target.id)
    await mkdir(folder, { recursive: true })
    const outfile = join(folder, binaryName(target))

    console.info(`Compiling ${target.id} -> ${outfile}`)
    // The same flags as `pnpm run compile`, so a release behaves like a local build: a compiled hog
    // never loads a .env or bunfig.toml from the folder it runs in.
    const build = Bun.spawn(
        [
            'bun',
            'build',
            '--compile',
            '--no-compile-autoload-dotenv',
            '--no-compile-autoload-bunfig',
            `--target=${target.bunTarget}`,
            ...defines,
            'src/index.ts',
            '--outfile',
            outfile,
        ],
        { cwd: HOG_ROOT, stdout: 'inherit', stderr: 'inherit' }
    )
    if ((await build.exited) !== 0) {
        console.error(`Compiling ${target.id} failed.`)
        process.exit(1)
    }
}
