import * as parser from '@babel/parser'
import traverse from '@babel/traverse'
import fs from 'fs'
import path from 'path'

// Parse dist/toolbar.js and check for anything that might trigger CSP script-src violations

// The threat model here is:
// * We're not trying to protect against an attacker hiding an eval like window["ev" + "al"]("...").
// * This is OK because any actual violations will be caught by the customer's actual CSP rules.
// * We are just trying to prevent false positives in the CSP report.
// * This script is just meant to protect against us accidentally adding evals, which wouldn't be maliciously hidden.

// Identifiers that become code when the *first* argument is a string
const UNSAFE_TIMERS = new Set(['setTimeout', 'setInterval', 'setImmediate', 'execScript'])
const FUNCTION_CTORS = new Set(['Function', 'AsyncFunction', 'GeneratorFunction', 'AsyncGeneratorFunction'])

// Known violations from vendored dependencies that we can't avoid.
// Each entry records the expected count and which dependency causes it.
// If the count changes (e.g. after a dependency version bump), update the count here.
const ALLOWED_VIOLATIONS = {
    'new Function()': {
        count: 5,
        source: 'pixi.js via @posthog/hedgehog-mode (4) + toolbarLogic CSP probe (1)',
    },
}

function main() {
    const filePath = 'dist/toolbar.js'
    const absPath = path.resolve(process.cwd(), filePath)
    const source = fs.readFileSync(absPath, 'utf-8')

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

    // Group violations by type
    const countsByType = {}
    for (const { type } of evals) {
        countsByType[type] = (countsByType[type] || 0) + 1
    }

    let hasUnexpected = false

    for (const [type, count] of Object.entries(countsByType)) {
        const allowed = ALLOWED_VIOLATIONS[type]
        if (allowed && count === allowed.count) {
            // All good, nothing to see here, move along
            continue
        } else if (allowed && count !== allowed.count) {
            console.error(
                `✗ ${type}: found ${count} occurrence(s), expected ${allowed.count} (${allowed.source}). Update ALLOWED_VIOLATIONS if this is intentional.`
            )
            hasUnexpected = true
        } else {
            console.error(`✗ ${type}: ${count} unexpected occurrence(s)`)
            hasUnexpected = true
        }
    }

    if (hasUnexpected) {
        evals.forEach(({ type, start: { line, column } }) => {
            const allowed = ALLOWED_VIOLATIONS[type]
            if (!allowed || countsByType[type] !== allowed.count) {
                console.error(`  ${type}: line ${line}:${column}`)
            }
        })
        process.exit(1)
    }
}

main()
