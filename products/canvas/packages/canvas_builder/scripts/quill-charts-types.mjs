import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const builderDirectory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = path.resolve(builderDirectory, '../../../..')
// The builder installs without dev dependencies, so borrow the frontend workspace's TypeScript.
const ts = createRequire(path.join(repoRoot, 'frontend/package.json'))('typescript')

const pinnedVersion = JSON.parse(readFileSync(path.join(builderDirectory, 'manifest.json'), 'utf8')).dependencies[
    '@posthog/quill-charts'
].version
// Read the published package, not node_modules: a local quill-charts build can overwrite node_modules without changing its version.
const downloadDirectory = realpathSync(mkdtempSync(path.join(os.tmpdir(), 'quill-charts-types-')))
execFileSync('npm', ['pack', `@posthog/quill-charts@${pinnedVersion}`, '--pack-destination', downloadDirectory], {
    stdio: ['ignore', 'ignore', 'inherit'],
})
execFileSync('tar', [
    '-xzf',
    path.join(downloadDirectory, `posthog-quill-charts-${pinnedVersion}.tgz`),
    '-C',
    downloadDirectory,
])
const packageDirectory = path.join(downloadDirectory, 'package')
const outputDirectory = path.join(
    repoRoot,
    'products/canvas/skills/building-react-quill-canvases/references/quill-charts'
)

const ENTRIES = {
    TimeSeriesLineChart: ['TimeSeriesLineChart'],
    TimeSeriesBarChart: ['TimeSeriesBarChart'],
    TimeSeriesComboChart: ['TimeSeriesComboChart'],
    LineChart: ['LineChart'],
    BarChart: ['BarChart'],
    ComboChart: ['ComboChart'],
    BarList: ['BarList'],
    ProportionBar: ['ProportionBar'],
    PieChart: ['PieChart'],
    FunnelChart: ['FunnelChart', 'funnelFromCounts'],
    ScatterChart: ['ScatterChart'],
    Heatmap: ['Heatmap'],
    SankeyChart: ['SankeyChart'],
    BoxPlot: ['BoxPlot'],
    SlopeChart: ['SlopeChart'],
    Sparkline: ['Sparkline'],
    MetricCard: ['MetricCard'],
    Chart: ['Chart', 'applyChartDefaults'],
    RadialChart: ['RadialChart'],
    ReferenceLine: ['ReferenceLine', 'ReferenceLines'],
    HighlightedRange: ['HighlightedRange'],
    ValueLabels: ['ValueLabels'],
    AxisTitles: ['AxisTitles'],
    Tooltip: ['DefaultTooltip', 'TooltipSurface', 'TooltipSwatch', 'TooltipFooter'],
}

const { version } = JSON.parse(readFileSync(path.join(packageDirectory, 'package.json'), 'utf8'))
const indexPath = path.join(packageDirectory, 'dist/index.d.ts')
const program = ts.createProgram([indexPath], {
    jsx: ts.JsxEmit.ReactJSX,
    moduleResolution: ts.ModuleResolutionKind.Bundler,
    module: ts.ModuleKind.ESNext,
    skipLibCheck: true,
    noEmit: true,
    types: [],
})
const checker = program.getTypeChecker()
const exported = new Map(
    checker
        .getExportsOfModule(checker.getSymbolAtLocation(program.getSourceFile(indexPath)))
        .map((symbol) => [symbol.name, symbol])
)

function resolve(symbol) {
    return symbol.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(symbol) : symbol
}

function ownStatement(declaration) {
    const statement = ts.isVariableDeclaration(declaration) ? declaration.parent.parent : declaration
    const file = statement.getSourceFile()
    return statement.parent === file && file.fileName.startsWith(packageDirectory) ? statement : undefined
}

function statementsOf(symbol) {
    return (resolve(symbol).declarations ?? []).map(ownStatement).filter(Boolean)
}

function collect(roots) {
    const seen = new Set()
    const queue = roots.flatMap(statementsOf)
    while (queue.length) {
        const statement = queue.shift()
        if (seen.has(statement)) {
            continue
        }
        seen.add(statement)
        const visit = (node) => {
            if (ts.isIdentifier(node)) {
                const symbol = checker.getSymbolAtLocation(node)
                if (symbol) {
                    queue.push(...statementsOf(symbol))
                }
            }
            ts.forEachChild(node, visit)
        }
        visit(statement)
    }
    return [...seen]
}

function print(statement) {
    const file = statement.getSourceFile()
    const docs = (ts.getLeadingCommentRanges(file.text, statement.getFullStart()) ?? [])
        .filter((range) => file.text.startsWith('/**', range.pos))
        .map((range) => file.text.slice(range.pos, range.end))
    return [...docs, statement.getText(file)].join('\n')
}

function namesOf(statements) {
    const names = statements.flatMap((statement) =>
        ts.isVariableStatement(statement)
            ? statement.declarationList.declarations.map((declaration) => declaration.name.getText())
            : statement.name
              ? [statement.name.getText()]
              : []
    )
    return [...new Set(names)]
}

function write(file, lines, statements) {
    const importable = namesOf(statements).filter((name) => exported.has(name))
    const header = [
        ...lines,
        `// Generated from @posthog/quill-charts ${version}, the version the canvas builder pins, by`,
        '// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.',
        `// Importable from '@posthog/quill-charts': ${importable.join(', ')}.`,
        '// Other declarations here are shapes to match, not names to import.',
    ]
    writeFileSync(path.join(outputDirectory, file), `${header.join('\n')}\n\n${statements.map(print).join('\n\n')}\n`)
}

const collected = Object.entries(ENTRIES).map(([name, roots]) => {
    const missing = roots.filter((root) => !exported.has(root))
    if (missing.length) {
        throw new Error(`@posthog/quill-charts ${version} no longer exports ${missing.join(', ')}`)
    }
    return [name, collect(roots.map((root) => exported.get(root)))]
})
const uses = new Map()
for (const [, statements] of collected) {
    for (const statement of statements) {
        uses.set(statement, (uses.get(statement) ?? 0) + 1)
    }
}
const SHARED_BY = 3
const core = [...uses.keys()].filter((statement) => uses.get(statement) >= SHARED_BY)

rmSync(outputDirectory, { recursive: true, force: true })
mkdirSync(outputDirectory, { recursive: true })
write('core.d.ts', [`// Types that ${SHARED_BY} or more quill-charts components share.`], core)
for (const [name, statements] of collected) {
    const own = statements.filter((statement) => !core.includes(statement))
    const shared = namesOf(statements.filter((statement) => core.includes(statement)))
    write(
        `${name}.d.ts`,
        [`// Types of \`${name}\`. Shared types it uses, declared in core.d.ts: ${shared.join(', ')}.`],
        own
    )
}
writeFileSync(
    path.join(outputDirectory, 'generated-from.json'),
    JSON.stringify({ package: '@posthog/quill-charts', version })
)
execFileSync(path.join(repoRoot, 'node_modules/.bin/oxfmt'), [outputDirectory], { cwd: repoRoot, stdio: 'ignore' })
rmSync(downloadDirectory, { recursive: true, force: true })
