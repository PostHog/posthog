import * as parser from '@babel/parser'
import traverse from '@babel/traverse'
import fs from 'fs'
import path from 'path'

import { eagerOutputs, jsOutputs, readToolbarMetafile } from './toolbar-metafile.mjs'

// Parse every shipped toolbar JS file (the dist/toolbar.js loader + the ESM app outputs in
// dist/toolbar/) and check for anything that might trigger CSP script-src violations.

// The threat model here is:
// * We're not trying to protect against an attacker hiding an eval like window["ev" + "al"]("...").
// * This is OK because any actual violations will be caught by the customer's actual CSP rules.
// * We are just trying to prevent false positives in the CSP report.
// * This script is just meant to protect against us accidentally adding evals, which wouldn't be maliciously hidden.

// Identifiers that become code when the *first* argument is a string
const UNSAFE_TIMERS = new Set(['setTimeout', 'setInterval', 'setImmediate', 'execScript'])
const FUNCTION_CTORS = new Set(['Function', 'AsyncFunction', 'GeneratorFunction', 'AsyncGeneratorFunction'])

// Known violations from vendored dependencies that we can't avoid, scoped to where they're
// allowed to live. If a count changes (e.g. after a dependency version bump), update it here.
// The loader is held to zero: it runs on every customer page that enables the toolbar, before
// the user interacts at all, so it must never show up in a CSP report.
const ALLOWED_VIOLATIONS = {
    'new Function()': {
        loader: 0,
        eager: 1, // toolbarLogic's deliberate CSP support probe
        total: 5, // + pixi.js via @posthog/hedgehog-mode (4), in the lazy hedgehog chunks
        source: 'toolbarLogic CSP probe (1, eager) + pixi.js via @posthog/hedgehog-mode (4, lazy)',
    },
}

function scanFile(filePath) {
    const source = fs.readFileSync(path.resolve(process.cwd(), filePath), 'utf-8')
    const ast = parser.parse(source, {
        sourceType: 'unambiguous',
    })

    const evals = []

    traverse.default(ast, {
        CallExpression(p) {
            const callee = p.get('callee')

            // eval(...)
            if (callee.isIdentifier({ name: 'eval' })) {
                if (p.node.loc) {
                    evals.push({
                        type: 'eval()',
                        start: p.node.loc.start,
                    })
                }
            }

            // window['eval'](...)
            else if (
                callee.isMemberExpression() &&
                callee.node.computed &&
                callee.get('object').isIdentifier({ name: 'window' }) &&
                callee.get('property').isStringLiteral({ value: 'eval' })
            ) {
                if (p.node.loc) {
                    evals.push({ type: 'window["eval"]()', start: p.node.loc.start })
                }
            }

            // === 3. setTimeout + other functions with a string argument
            else if (
                (callee.isIdentifier() && UNSAFE_TIMERS.has(callee.node.name)) ||
                (callee.isMemberExpression() &&
                    !callee.node.computed &&
                    callee.get('object').isIdentifier({ name: 'window' }) &&
                    callee.get('property').isIdentifier() &&
                    UNSAFE_TIMERS.has(callee.get('property').node.name))
            ) {
                const firstArg = p.get('arguments')[0]
                if (firstArg?.isStringLiteral()) {
                    evals.push({ type: `${callee.node.name}(string)`, start: p.node.loc })
                }
            }
        },

        NewExpression(p) {
            const callee = p.get('callee')

            // new Function(...) + other Function constructors
            if (callee.isIdentifier() && FUNCTION_CTORS.has(callee.node.name)) {
                evals.push({
                    type: `new ${callee.node.name}()`,
                    start: p.node.loc.start,
                })
            }
        },
    })

    return evals.map((v) => ({ ...v, file: filePath }))
}

function countByType(violations) {
    const counts = {}
    for (const { type } of violations) {
        counts[type] = (counts[type] || 0) + 1
    }
    return counts
}

function main() {
    const metafile = readToolbarMetafile()
    const outputs = metafile.outputs

    const loaderViolations = scanFile('dist/toolbar.js')
    const eagerJs = [...eagerOutputs(outputs)].filter((o) => o.endsWith('.js'))
    const appViolations = jsOutputs(outputs).flatMap((file) => scanFile(file))
    const eagerViolations = appViolations.filter((v) => eagerJs.includes(v.file))

    const scopes = [
        { name: 'loader (dist/toolbar.js)', key: 'loader', counts: countByType(loaderViolations) },
        { name: 'eager app closure', key: 'eager', counts: countByType(eagerViolations) },
        {
            name: 'all app outputs + loader',
            key: 'total',
            counts: countByType([...loaderViolations, ...appViolations]),
        },
    ]

    let hasUnexpected = false

    for (const { name, key, counts } of scopes) {
        const typesToCheck = new Set([...Object.keys(counts), ...Object.keys(ALLOWED_VIOLATIONS)])
        for (const type of typesToCheck) {
            const found = counts[type] || 0
            const expected = ALLOWED_VIOLATIONS[type]?.[key] ?? 0
            if (found !== expected) {
                const source = ALLOWED_VIOLATIONS[type]?.source
                console.error(
                    `✗ ${type} in ${name}: found ${found}, expected ${expected}${source ? ` (${source})` : ''}. ` +
                        'Update ALLOWED_VIOLATIONS if this is intentional.'
                )
                hasUnexpected = true
            }
        }
    }

    if (hasUnexpected) {
        for (const { type, file, start } of [...loaderViolations, ...appViolations]) {
            console.error(`  ${type}: ${file} line ${start.line}:${start.column}`)
        }
        process.exit(1)
    }
}

main()
