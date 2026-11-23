import assert from 'node:assert/strict'
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { z } from 'zod'

import { parseJson } from '@/core/json'
import { Description } from '@/stack/evaluation'

import { installStackPackages } from '../test/stack-project'

const binary = resolve(process.argv[2] ?? 'dist/hog')
const repo = resolve(import.meta.dir, '../..')
const work = await mkdtemp(join(tmpdir(), 'hog-binary-check-'))
const Result = z.object({
    ok: z.literal(true),
    description: Description,
    typeCheck: z.object({ status: z.literal('passed') }),
    problems: z.array(z.unknown()).length(0),
    output: z.object({ stdout: z.string(), stderr: z.string() }),
})
// A ported tile keeps its original's grid fields, which PostHog drops, so each one warns.
const Port = Result.extend({
    problems: z.array(z.object({ severity: z.literal('warning'), code: z.literal('layout_field_dropped') })),
})
const Failure = z.object({ error: z.object({ code: z.string(), output: z.object({ stdout: z.string() }) }) })
const unreadable = { code: 'invalid_binary_output' }

interface CheckRun {
    code: number
    stdout: string
    stderr: string
}

async function check(cwd: string, ...args: string[]): Promise<CheckRun> {
    const child = Bun.spawn([binary, 'check', ...args], {
        cwd,
        env: { SystemRoot: process.env.SystemRoot, HOME: work, HOG_HOME: work, NO_COLOR: '1' },
        stdin: 'ignore',
        stdout: 'pipe',
        stderr: 'pipe',
        timeout: 60_000,
        killSignal: 'SIGKILL',
    })
    const [code, stdout, stderr] = await Promise.all([
        child.exited,
        new Response(child.stdout).text(),
        new Response(child.stderr).text(),
    ])
    return { code, stdout, stderr }
}

try {
    const port = await check(repo, '--stack', 'slo-monitoring', '--raw')
    assert.equal(port.code, 0, port.stderr || port.stdout)
    const saved = await readFile(join(repo, '.ph/us/project-2/slo-monitoring/description.json'), 'utf8')
    assert.deepEqual(parseJson(port.stdout, Port, unreadable).description, parseJson(saved, Description, unreadable))
    console.info('Passed SLO description check.')

    const folder = join(work, '.ph')
    await mkdir(folder)
    await mkdir(join(work, '.git'))
    installStackPackages(folder)
    const entry = join(folder, 'index.ts')
    await writeFile(
        entry,
        [
            "import { dashboard } from '@posthog/sdk/define'",
            "console.log('Loading definitions')",
            "console.error('A note from the folder')",
            "export const overview = dashboard('overview', { name: 'Overview', tiles: [] })",
        ].join('\n')
    )
    const agent = await check(work, '--raw')
    assert.equal(agent.code, 0, agent.stderr || agent.stdout)
    assert.equal(agent.stderr, '')
    assert.equal(agent.stdout.trim().split('\n').length, 1)
    const loaded = parseJson(agent.stdout, Result, unreadable)
    assert.deepEqual(
        loaded.description.resources.map(({ kind, key }) => [kind, key]),
        [['dashboard', 'overview']]
    )
    assert.deepEqual(loaded.output, { stdout: 'Loading definitions\n', stderr: 'A note from the folder\n' })
    const human = await check(work, '-o', 'text')
    assert.equal(human.code, 0, human.stderr || human.stdout)
    assert.match(human.stdout, /Captured stdout: Loading definitions/)
    assert.match(human.stdout, /Captured stderr: A note from the folder/)
    console.info('Passed external SDK import and captured output checks.')

    if (process.platform !== 'win32') {
        const pidFile = join(work, 'sleeper.pid')
        await writeFile(
            entry,
            [
                '// @ts-nocheck',
                "import { spawn } from 'node:child_process'",
                "import { writeFileSync } from 'node:fs'",
                "import { dashboard } from '@posthog/sdk/define'",
                "const sleeper = spawn('/bin/sleep', ['60'], { stdio: 'inherit' })",
                `writeFileSync(${JSON.stringify(pidFile)}, String(sleeper.pid))`,
                "export const overview = dashboard('overview', { name: 'Overview', tiles: [] })",
            ].join('\n')
        )
        const started = Date.now()
        const held = await check(work, '--raw')
        assert.equal(held.code, 0, held.stderr || held.stdout)
        assert.ok(Date.now() - started < 20_000, 'A process the definitions started held the check open.')
        const pid = Number(await readFile(pidFile, 'utf8'))
        const alive = (): boolean => {
            try {
                process.kill(pid, 0)
                return true
            } catch {
                return false
            }
        }
        for (let tries = 0; alive() && tries < 40; tries++) {
            await Bun.sleep(50)
        }
        assert.equal(alive(), false, 'A process the definitions started outlived the check.')
        console.info('Passed started process check.')
    }

    await writeFile(entry, "console.log('Starting loop')\nwhile (true) {}")
    const loop = await check(work)
    assert.equal(loop.code, 1, loop.stderr || loop.stdout)
    assert.equal(loop.stdout, '')
    const { error } = parseJson(loop.stderr, Failure, unreadable)
    assert.equal(error.code, 'stack_evaluation_timeout')
    assert.equal(error.output.stdout, 'Starting loop\n')
    console.info('Passed evaluation timeout check.')
} finally {
    await rm(work, { recursive: true, force: true })
}
