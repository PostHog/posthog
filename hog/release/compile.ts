// Bun cross-compiles, so one machine builds every target. Without --version the build is a dev build,
// which never checks for updates. Run `pnpm run build:mcp` first: the binary embeds the MCP library.

import { existsSync } from 'node:fs'
import { mkdir } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { parseArgs } from 'node:util'

import { binaryName } from '../src/updates/targets'
import { BUILD_OPTIONS, buildTargets, HOG_ROOT, RELEASE_FOLDER, run, targetFolder } from './shared'

const MCP_LIBRARY = resolve(HOG_ROOT, '../services/mcp/dist/cli-library.mjs')

const { values } = parseArgs({
    options: { ...BUILD_OPTIONS, out: { type: 'string', default: RELEASE_FOLDER }, 'build-date': { type: 'string' } },
})
const { version } = values
const targets = buildTargets(values.target, version)

if (!existsSync(MCP_LIBRARY)) {
    console.error(`Missing ${MCP_LIBRARY}. Run \`pnpm --filter hog build:mcp\` first.`)
    process.exit(1)
}

const buildDate = values['build-date'] ?? new Date().toISOString()
if (Number.isNaN(Date.parse(buildDate))) {
    console.error(`--build-date ${buildDate} isn't a date.`)
    process.exit(1)
}

const defines =
    version === undefined
        ? []
        : [
              `--define=HOG_RELEASE_VERSION=${JSON.stringify(version)}`,
              `--define=HOG_BUILD_DATE=${JSON.stringify(buildDate)}`,
          ]

for (const target of targets) {
    const folder = targetFolder(values.out, target)
    await mkdir(folder, { recursive: true })
    const outfile = join(folder, binaryName(target))

    console.info(`Compiling ${target.id} -> ${outfile}`)
    // The flags of `pnpm run compile`: a compiled hog never loads a .env or bunfig.toml from its folder.
    await run(
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
        HOG_ROOT
    )
}
