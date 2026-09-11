const { execFileSync, spawnSync } = require('node:child_process')
const { readFileSync } = require('node:fs')
const { dirname, join } = require('node:path')
const ts = require('typescript')

const oxlint = join(dirname(require.resolve('oxlint/package.json')), 'bin/oxlint')
const args = [oxlint, '-c', '.oxlintrc.json', ...process.argv.slice(2)]

function checkDisableDirectives(filename) {
    const text = readFileSync(filename, 'utf8')
    const source = ts.createSourceFile(filename, text, ts.ScriptTarget.Latest)
    const seen = new Set()
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
                const { line, character } = source.getLineAndCharacterOfPosition(range.pos)
                console.error(
                    `${filename}:${line + 1}:${character + 1}: error no-unlimited-disable: Specify rule names in lint disable directives.`
                )
                valid = false
            }
        }
    }

    visit(source)
    return valid
}

// Oxlint can suppress a plugin's own directive error, so reject blanket disables before linting.
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
