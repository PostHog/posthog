#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'

// Warns when a service integration icon (frontend/public/services/*) is committed
// oversized. These icons are mapped per IntegrationKind in lib/integrations/utils.ts,
// which is statically reachable from AuthenticatedShell — so each one counts against
// the eager graph budget that every authenticated page pays for (#32479). A
// well-optimized 256x256 PNG logo is comfortably under this budget; anything far above
// it is almost always an unoptimized export. This is a non-blocking nudge at commit
// time; frontend/bin/check-eager-graph.mjs remains the hard CI backstop on the total.
//
// Invoked via lint-staged with the staged icon paths appended as arguments.

const BUDGET_BYTES = 25 * 1024
const RASTER = new Set(['.png', '.jpg', '.jpeg', '.gif'])

const offenders = []
for (const file of process.argv.slice(2)) {
    if (!RASTER.has(path.extname(file).toLowerCase()) || !fs.existsSync(file)) {
        continue
    }
    const bytes = fs.statSync(file).size
    if (bytes > BUDGET_BYTES) {
        offenders.push({ file, bytes })
    }
}

if (offenders.length) {
    const yellow = (s) => `\x1b[33m${s}\x1b[0m`
    const kib = (b) => `${(b / 1024).toFixed(1)} KiB`
    process.stderr.write(
        yellow(
            `\nWarning: service icon${offenders.length > 1 ? 's' : ''} over ${kib(BUDGET_BYTES)} — these are eagerly ` +
                `reachable from AuthenticatedShell and inflate the eager graph budget:\n` +
                offenders.map((o) => `  ${kib(o.bytes).padStart(10)}  ${o.file}`).join('\n') +
                `\nCompress before committing (e.g. an octree 256-colour PNG palette keeps logos visually identical at a ` +
                `fraction of the size). If the asset genuinely needs to be this large, it's fine to proceed.\n\n`
        )
    )
}

// Non-blocking: a nudge, not a gate.
process.exit(0)
