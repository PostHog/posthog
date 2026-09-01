#!/usr/bin/env node
/**
 * Cyclomatic complexity linter for TypeScript/JavaScript files.
 *
 * Counts decision points per function (eslint `complexity` semantics: each
 * function starts at 1; if/loops/case/catch/ternary/&&/||/?? add 1). Oxlint has
 * no complexity rule yet, so this uses the TypeScript compiler API directly.
 *
 * Usage:
 *   node bin/lint-complexity.mjs [--json] [--report <path>] <files...>
 *
 * Findings above WARN_AT are warnings; the check never fails a job (advisory
 * while the pre-existing backlog settles). `--json` emits the findings as
 * JSON for `hogli lint:complexity`, which owns human-readable output.
 * `--report <path>` writes the same JSON to a file while printing human
 * output and annotations (used by CI to post the CI report section). A test
 * binds the thresholds here to the Python side (test_complexity_lint.py).
 */

import { existsSync, readFileSync, writeFileSync } from 'fs'
import { createRequire } from 'module'
import { dirname, resolve } from 'path'
import { fileURLToPath } from 'url'

// typescript is a dependency of @posthog/frontend, not the workspace root, so
// pnpm's isolated layout only links it under frontend/node_modules.
const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(resolve(repoRoot, 'frontend', 'package.json'))
const ts = require('typescript')

const WARN_AT = 10

const FUNCTION_KINDS = new Set([
    ts.SyntaxKind.FunctionDeclaration,
    ts.SyntaxKind.FunctionExpression,
    ts.SyntaxKind.ArrowFunction,
    ts.SyntaxKind.MethodDeclaration,
    ts.SyntaxKind.Constructor,
    ts.SyntaxKind.GetAccessor,
    ts.SyntaxKind.SetAccessor,
])

const BRANCH_KINDS = new Set([
    ts.SyntaxKind.IfStatement,
    ts.SyntaxKind.ForStatement,
    ts.SyntaxKind.ForInStatement,
    ts.SyntaxKind.ForOfStatement,
    ts.SyntaxKind.WhileStatement,
    ts.SyntaxKind.DoStatement,
    ts.SyntaxKind.CaseClause,
    ts.SyntaxKind.CatchClause,
    ts.SyntaxKind.ConditionalExpression,
])

const SHORT_CIRCUIT_OPERATORS = new Set([
    ts.SyntaxKind.AmpersandAmpersandToken,
    ts.SyntaxKind.BarBarToken,
    ts.SyntaxKind.QuestionQuestionToken,
    ts.SyntaxKind.AmpersandAmpersandEqualsToken,
    ts.SyntaxKind.BarBarEqualsToken,
    ts.SyntaxKind.QuestionQuestionEqualsToken,
])

function isBranchNode(node) {
    if (BRANCH_KINDS.has(node.kind)) {
        return true
    }
    return ts.isBinaryExpression(node) && SHORT_CIRCUIT_OPERATORS.has(node.operatorToken.kind)
}

// Parent node kinds that hold the name a function expression is assigned to,
// e.g. `const foo = () => {}`, `{ foo: () => {} }`, `class C { foo = () => {} }`.
const NAME_HOLDER_CHECKS = [ts.isVariableDeclaration, ts.isPropertyAssignment, ts.isPropertyDeclaration]

function functionName(node) {
    if (node.name && ts.isIdentifier(node.name)) {
        return node.name.text
    }
    const parent = node.parent
    if (parent && NAME_HOLDER_CHECKS.some((isNameHolder) => isNameHolder(parent)) && ts.isIdentifier(parent.name)) {
        return parent.name.text
    }
    if (node.kind === ts.SyntaxKind.Constructor) {
        return 'constructor'
    }
    return '<anonymous>'
}

function lintFile(filePath) {
    const source = readFileSync(filePath, 'utf8')
    const scriptKind = filePath.endsWith('x') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
    const sourceFile = ts.createSourceFile(filePath, source, ts.ScriptTarget.Latest, true, scriptKind)
    const findings = []

    function walk(node, frame) {
        if (FUNCTION_KINDS.has(node.kind)) {
            const inner = { complexity: 1 }
            node.forEachChild((child) => walk(child, inner))
            const { line, character } = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile))
            findings.push({
                file: filePath,
                line: line + 1,
                column: character + 1,
                name: functionName(node),
                complexity: inner.complexity,
            })
            return
        }
        if (frame && isBranchNode(node)) {
            frame.complexity++
        }
        node.forEachChild((child) => walk(child, frame))
    }

    walk(sourceFile, null)
    return findings
}

// Not ours to lint: generated code, pnpm installs, type declarations, and
// products/desktop (Biome-linted by its own desktop-* CI).
const EXCLUDED = [/(^|\/)node_modules\//, /(^|\/)generated\//, /\.d\.ts$/, /^products\/desktop\//]

const args = process.argv.slice(2)
const asJson = args.includes('--json')
const reportIdx = args.indexOf('--report')
const reportPath = reportIdx === -1 ? null : args[reportIdx + 1]
const files = args.filter((arg, index) => arg !== '--json' && arg !== '--report' && index !== reportIdx + 1)

const findings = []
for (const file of files) {
    if (!/\.(ts|tsx|js|jsx|mjs|cjs)$/.test(file) || EXCLUDED.some((pattern) => pattern.test(file))) {
        continue
    }
    if (!existsSync(file)) {
        continue
    }
    findings.push(...lintFile(file).filter((finding) => finding.complexity > WARN_AT))
}

for (const finding of findings) {
    if (asJson) {
        continue
    }
    const message = `\`${finding.name}\` has cyclomatic complexity ${finding.complexity} (warn >${WARN_AT})`
    console.info(`${finding.file}:${finding.line}:${finding.column}: warning: ${message}`)
    if (process.env.GITHUB_ACTIONS === 'true') {
        console.info(
            `::warning file=${finding.file},line=${finding.line},col=${finding.column},title=lint:complexity::${message}`
        )
    }
}
if (asJson) {
    console.info(JSON.stringify(findings))
}
if (reportPath) {
    writeFileSync(reportPath, JSON.stringify(findings))
}
