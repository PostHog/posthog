const { execFileSync, spawnSync } = require('node:child_process')
const { readFileSync, writeFileSync } = require('node:fs')
const { dirname, join } = require('node:path')
const ts = require('typescript')

const oxlint = join(dirname(require.resolve('oxlint/package.json')), 'bin/oxlint')
const args = [oxlint, '-c', '.oxlintrc.nodejs.json', ...process.argv.slice(2)]
const fix = args.includes('--fix')

function checkDisableDirectives(filename) {
    const text = readFileSync(filename, 'utf8')
    const source = ts.createSourceFile(filename, text, ts.ScriptTarget.Latest)
    const seen = new Set()
    const removals = []
    let valid = true

    function visit(node) {
        const children = node.getChildren(source)
        if (children.length) {
            children.forEach(visit)
            return
        }
        for (const range of [
            ...(ts.getLeadingCommentRanges(text, node.pos) ?? []),
            ...(ts.getTrailingCommentRanges(text, node.pos) ?? []),
        ]) {
            if (seen.has(range.pos)) {
                continue
            }
            seen.add(range.pos)
            const comment = text
                .slice(range.pos + 2, range.end)
                .replace(/\*\/$/, '')
                .trim()
            if (/^(?:eslint|oxlint)-disable(?:-next-line|-line)?(?:\s+--.*)?\s*$/s.test(comment)) {
                if (fix) {
                    removals.push(range)
                    continue
                }
                const { line, character } = source.getLineAndCharacterOfPosition(range.pos)
                console.error(
                    `${filename}:${line + 1}:${character + 1}: error no-unlimited-disable: Specify rule names in lint disable directives.`
                )
                valid = false
            }
        }
    }

    visit(source)
    if (removals.length) {
        let fixed = text
        for (const { pos, end } of removals.sort((a, b) => b.pos - a.pos)) {
            fixed = fixed.slice(0, pos) + fixed.slice(pos, end).replace(/[^\r\n]/g, ' ') + fixed.slice(end)
        }
        writeFileSync(filename, fixed)
    }
    return valid
}

// Oxlint can suppress a plugin's own directive error. Remove blanket disables in fix mode so generated code is linted.
const files = execFileSync(process.execPath, [...args, '--debug', 'files'], { encoding: 'utf8' })
    .trim()
    .split('\n')
    .filter(Boolean)
const valid = files.map(checkDisableDirectives).every(Boolean)
if (!valid) {
    process.exit(1)
}
const result = spawnSync(process.execPath, args, { stdio: 'inherit' })
process.exit(result.status ?? 1)
