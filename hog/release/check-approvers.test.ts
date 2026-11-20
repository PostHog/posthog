import { beforeAll, describe, expect, test } from 'bun:test'
import { execFileSync, spawnSync } from 'node:child_process'
import { chmod, mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'

const CHECKER = join(import.meta.dir, 'check-approvers.sh')
// The release workflow runs the checker on Linux. It needs Bash 4 for mapfile, and macOS ships Bash 3.2.
const BASH_CANDIDATES = ['bash', '/opt/homebrew/bin/bash', '/usr/local/bin/bash']
const BASH = BASH_CANDIDATES.find(
    (candidate) => spawnSync(candidate, ['-c', 'mapfile -t lines </dev/null']).status === 0
)
if (!BASH) {
    console.warn(`Skipping the check-approvers.sh tests: none of ${BASH_CANDIDATES.join(', ')} is Bash 4 or later.`)
}

// Answers the checker's GraphQL queries from the test repository: each commit's author opened its pull
// request, which the subject names as (#<number>).
const FAKE_GH = `#!/usr/bin/env bash
set -euo pipefail
query=$(printf '%s\\n' "$@" | sed -n 's/^query=//p')
if [[ "$*" == *--paginate* ]]; then
    exit 0
fi
fields='{}'
for sha in $(grep -oE 'c[0-9a-f]{40}' <<<"$query" | cut -c2- | sort -u); do
    login=$(git log -1 --format=%an "$sha")
    number=$(git log -1 --format=%s "$sha" | sed -n 's/.*(#\\([0-9]*\\))$/\\1/p')
    fields=$(jq --arg key "c$sha" --arg login "$login" --argjson number "$number" '. + {($key): {
        authors: {totalCount: 1, nodes: [{user: {login: $login}}]},
        associatedPullRequests: {nodes: [{number: $number, title: "change", merged: true,
            author: {login: $login, __typename: "User"}, mergedBy: {login: "trunk-io[bot]", __typename: "Bot"}}]}
    }}' <<<"$fields")
done
jq -n --argjson fields "$fields" '{data: {repository: $fields}}'
`

let repo: string
let base: string
let fakeBin: string

async function commit(path: string, author: string, subject: string): Promise<void> {
    await mkdir(join(repo, dirname(path)), { recursive: true })
    await writeFile(join(repo, path), `${subject}\n`)
    execFileSync('git', ['add', path], { cwd: repo })
    execFileSync(
        'git',
        [
            '-c',
            `user.name=${author}`,
            '-c',
            'user.email=dev@example.com',
            '-c',
            'commit.gpgsign=false',
            'commit',
            '-q',
            '-m',
            subject,
        ],
        { cwd: repo }
    )
}

beforeAll(async () => {
    repo = await mkdtemp(join(tmpdir(), 'hog-approvers-'))
    execFileSync('git', ['init', '-q'], { cwd: repo })
    await commit('README.md', 'founder', 'start (#1)')
    base = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim()

    await commit('hog/.sampo/changesets/weekly-login.md', 'alice', 'feat(cli): add a changeset (#2)')
    await commit('services/mcp/src/tools/exec.ts', 'bob', 'fix(mcp): change compiled code (#3)')
    await commit('docs/notes.md', 'carol', 'chore: change docs (#4)')
    await commit('products/surveys/mcp/tools.yaml', 'dana', 'feat(surveys): change a product tool (#5)')
    await commit('hog/release/check-approvers.sh', 'erin', 'chore(cli): change the approver check (#6)')
    await commit('packages/charts/index.ts', 'hana', 'feat(charts): add a package hog starts to build from (#9)')
    await commit('drafts/exec-helper.ts', 'frank', 'chore: draft a helper (#7)')
    execFileSync('git', ['mv', 'drafts/exec-helper.ts', 'services/mcp/src/tools/exec-helper.ts'], { cwd: repo })
    execFileSync(
        'git',
        [
            '-c',
            'user.name=gina',
            '-c',
            'user.email=dev@example.com',
            '-c',
            'commit.gpgsign=false',
            'commit',
            '-q',
            '-m',
            'refactor(mcp): move the helper in (#8)',
        ],
        { cwd: repo }
    )

    fakeBin = await mkdtemp(join(tmpdir(), 'hog-fake-gh-'))
    await writeFile(join(fakeBin, 'gh'), FAKE_GH)
    await chmod(join(fakeBin, 'gh'), 0o755)
})

async function check(approver: string, extraPaths?: string[]): Promise<{ status: number | null; output: string }> {
    const output = join(repo, '.github-output')
    await writeFile(output, '')
    const options: string[] = []
    if (extraPaths) {
        await writeFile(join(repo, '.extra-paths'), extraPaths.join('\n'))
        options.push('--extra-paths', join(repo, '.extra-paths'))
    }

    const run = spawnSync(BASH!, [CHECKER, ...options, base, 'HEAD', approver], {
        cwd: repo,
        env: {
            ...process.env,
            PATH: `${fakeBin}:${process.env.PATH}`,
            GH_TOKEN: 'token',
            REPOSITORY: 'PostHog/posthog',
            GITHUB_OUTPUT: output,
        },
    })
    return { status: run.status, output: await readFile(output, 'utf8') }
}

describe.skipIf(!BASH)('check-approvers.sh', () => {
    test.each([
        ['the author of a changeset', 'alice', 'alice (#2)'],
        ['the author of a change to the MCP code', 'bob', 'bob (#3)'],
        ["the author of a change to a product's MCP tools", 'dana', 'dana (#5)'],
        ['the author of a change to the approver check itself', 'erin', 'erin (#6)'],
        ['the author of a move into the MCP code', 'gina', 'gina (#8)'],
    ])('blocks %s', async (_name, approver, violation) => {
        const result = await check(approver)

        expect(result.status).toBe(1)
        expect(result.output).toBe(`violations=${violation}\n`)
    })

    test.each([
        ['a change hog does not compile', 'carol'],
        ['a file before it moved into the MCP code, when hog did not compile it', 'frank'],
        ['a path outside the release paths when the caller adds none', 'hana'],
    ])('clears the author of %s', async (_name, approver) => {
        const result = await check(approver)

        expect(result).toEqual({ status: 0, output: '' })
    })

    test('blocks the author of a change to a path the caller adds', async () => {
        const result = await check('hana', ['packages/charts'])

        expect(result).toEqual({ status: 1, output: 'violations=hana (#9)\n' })
    })

    test.each([
        ['a glob', ['packages/*']],
        ['a pathspec magic word', [':(glob)packages/**']],
        ['a path that climbs out', ['hog/../packages/charts']],
    ])('stops on an extra path that is %s', async (_name, extraPaths) => {
        const result = await check('hana', extraPaths)

        expect(result).toEqual({ status: 1, output: '' })
    })
})
