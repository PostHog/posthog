#!/usr/bin/env node
/**
 * Cyclomatic complexity linter for TypeScript/JavaScript files.
 *
 * Counts decision points per function (eslint `complexity` semantics: each
 * function starts at 1; if/loops/case/catch/ternary/&&/||/?? add 1). Oxlint has
 * no complexity rule yet, so this uses the TypeScript compiler API directly.
 *
 * Usage:
 *   node bin/lint-complexity.mjs [--json] <files...>
 *
 * Functions above WARN_AT are warnings, above ERROR_AT errors; only errors exit
 * non-zero. `--json` emits the findings as JSON for `hogli lint:complexity`,
 * which owns all human-readable output. A test binds the thresholds here to the
 * Python side (test_complexity_lint.py) so the two cannot drift.
 */

import { existsSync, readFileSync } from 'fs'
import { createRequire } from 'module'
import { dirname, resolve } from 'path'
import { fileURLToPath } from 'url'

// typescript is a dependency of @posthog/frontend, not the workspace root, so
// pnpm's isolated layout only links it under frontend/node_modules.
const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(resolve(repoRoot, 'frontend', 'package.json'))
const ts = require('typescript')

const WARN_AT = 10
const ERROR_AT = 15

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

function functionName(node) {
    if (node.name && ts.isIdentifier(node.name)) {
        return node.name.text
    }
    const parent = node.parent
    if (parent && ts.isVariableDeclaration(parent) && ts.isIdentifier(parent.name)) {
        return parent.name.text
    }
    if (parent && ts.isPropertyAssignment(parent) && ts.isIdentifier(parent.name)) {
        return parent.name.text
    }
    if (parent && ts.isPropertyDeclaration(parent) && ts.isIdentifier(parent.name)) {
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
const files = args.filter((arg) => arg !== '--json')

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

let errors = 0
for (const finding of findings) {
    const severity = finding.complexity > ERROR_AT ? 'error' : 'warning'
    errors += severity === 'error'
    if (asJson) {
        continue
    }
    const message = `\`${finding.name}\` has cyclomatic complexity ${finding.complexity} (warn >${WARN_AT}, error >${ERROR_AT})`
    console.info(`${finding.file}:${finding.line}:${finding.column} ${severity}: ${message}`)
    if (process.env.GITHUB_ACTIONS === 'true') {
        console.info(
            `::${severity} file=${finding.file},line=${finding.line},col=${finding.column},title=lint:complexity::${message}`
        )
    }
}
if (asJson) {
    console.info(JSON.stringify(findings))
}
process.exit(errors > 0 ? 1 : 0)
