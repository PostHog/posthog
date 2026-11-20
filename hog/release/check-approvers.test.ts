import { beforeAll, describe, expect, test } from 'bun:test'
import { execFileSync, spawnSync } from 'node:child_process'
import { chmod, mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'

const CHECKER = join(import.meta.dir, 'check-approvers.sh')
const COMPILED_FILE = 'services/mcp/src/tools/exec.ts'

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
    await commit(COMPILED_FILE, 'bob', 'fix(mcp): change compiled code (#3)')
    await commit('docs/notes.md', 'carol', 'chore: change docs (#4)')

    fakeBin = await mkdtemp(join(tmpdir(), 'hog-fake-gh-'))
    await writeFile(join(fakeBin, 'gh'), FAKE_GH)
    await chmod(join(fakeBin, 'gh'), 0o755)
})

async function check(
    approver: string,
    files: string[] | undefined
): Promise<{ status: number | null; output: string }> {
    const output = join(repo, '.github-output')
    await writeFile(output, '')
    const options: string[] = []
    if (files) {
        await writeFile(join(repo, '.compiled-files'), files.join('\n'))
        options.push('--files', join(repo, '.compiled-files'))
    }

    const run = spawnSync('bash', [CHECKER, ...options, base, 'HEAD', approver], {
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

describe('check-approvers.sh', () => {
    test.each([
        ['the author of a changeset', 'alice', undefined, 'alice (#2)'],
        ['the author of a compiled change, with the compiled files listed', 'bob', [COMPILED_FILE], 'bob (#3)'],
        ['the author of a changeset, with the compiled files listed', 'alice', [COMPILED_FILE], 'alice (#2)'],
    ])('blocks %s', async (_name, approver, files, violation) => {
        const result = await check(approver, files)

        expect(result.status).toBe(1)
        expect(result.output).toBe(`violations=${violation}\n`)
    })

    test.each([
        ['the author of a compiled change, without the compiled files', 'bob', undefined],
        ['the author of a change hog does not compile', 'carol', [COMPILED_FILE]],
    ])('clears %s', async (_name, approver, files) => {
        const result = await check(approver, files)

        expect(result).toEqual({ status: 0, output: '' })
    })
})
