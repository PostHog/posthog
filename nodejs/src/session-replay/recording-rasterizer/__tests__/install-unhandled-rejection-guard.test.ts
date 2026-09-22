import { execFile } from 'child_process'
import * as fs from 'fs/promises'
import * as os from 'os'
import * as path from 'path'

// The guard exists because closing a page to abort a capture rejects the CDP call
// puppeteer-capture has in flight, and that rejection belongs to no promise the worker
// awaits. Node terminates the process on an unhandled rejection, so one bad render
// killed every in-flight render on the pod. Proving process survival needs a real
// process boundary; no in-process mock can, so this test runs a fixture child.

const FIXTURE_SCRIPT = `
const { installUnhandledRejectionGuard } = require('./install-unhandled-rejection-guard')
const noopLogger = { error: () => {} }
const mode = process.argv[2]
if (mode !== 'unguarded') {
    installUnhandledRejectionGuard(noopLogger)
}
// The rejection shape from the bug: a promise nothing awaits rejects while the
// process otherwise has work left to do.
const rejectUnawaited = () =>
    Promise.reject(new Error('TargetCloseError: Protocol error (Runtime.evaluate): Target closed'))
if (mode === 'flood') {
    for (let i = 0; i < 51; i++) {
        rejectUnawaited()
    }
    // All 51 rejections drain in one batch, so the guard disarms without a final one
    // to kill the process. The next rejection is the proof the guard is disarmed.
    setTimeout(rejectUnawaited, 10)
} else {
    rejectUnawaited()
}
setTimeout(() => {
    process.stdout.write('still-alive')
}, 50)
`

function exec(command: string, args: string[]): Promise<{ code: number; stdout: string; stderr: string }> {
    return new Promise((resolve) => {
        execFile(command, args, (err, stdout, stderr) => {
            // A non-zero exit reports as err with the code attached; resolve, not reject.
            const code = (err as NodeJS.ErrnoException | null)?.code
            resolve({ code: typeof code === 'number' ? code : err ? 1 : 0, stdout: String(stdout), stderr: String(stderr) })
        })
    })
}

describe('installUnhandledRejectionGuard', () => {
    let dir: string

    // The unhandled-rejection mode decides survival, so the child must not inherit a
    // parent NODE_OPTIONS that switches it to warn (where an unguarded child lives).
    const childEnv = { ...process.env, NODE_OPTIONS: '' }
    const node = (fixtureArgs: string[]): { command: string; args: string[]; env: NodeJS.ProcessEnv } => ({
        command: 'node',
        args: ['--unhandled-rejections=throw', path.join(dir, 'fixture.js'), ...fixtureArgs],
        env: childEnv,
    })

    const run = async (mode: string): Promise<{ code: number; stdout: string }> => {
        const { command, args, env } = node([mode])
        return await new Promise((resolve) => {
            execFile(command, args, { env }, (err, stdout) => {
                const code = (err as NodeJS.ErrnoException | null)?.code
                resolve({ code: typeof code === 'number' ? code : err ? 1 : 0, stdout: String(stdout) })
            })
        })
    }

    beforeAll(async () => {
        dir = await fs.mkdtemp(path.join(os.tmpdir(), 'rasterizer-guard-'))
        const tsc = require.resolve('typescript/bin/tsc')
        // The guard module has no ~ imports so plain tsc compiles it without the workspace config.
        const compilation = await exec('node', [
            tsc,
            path.resolve(__dirname, '../temporal/install-unhandled-rejection-guard.ts'),
            '--ignoreConfig',
            '--module',
            'commonjs',
            '--target',
            'es2022',
            '--skipLibCheck',
            '--types',
            'node',
            '--outDir',
            dir,
        ])
        // Without this check a failed compile degrades into MODULE_NOT_FOUND in the child,
        // and the failure points nowhere near the guard.
        expect(compilation.code).toBe(0)
        await fs.writeFile(path.join(dir, 'fixture.js'), FIXTURE_SCRIPT)
    })

    afterAll(async () => {
        if (dir) {
            await fs.rm(dir, { recursive: true, force: true })
        }
    })

    it('keeps the process alive when a promise nothing awaits rejects', async () => {
        const result = await run('guarded')

        expect(result.code).toBe(0)
        expect(result.stdout).toContain('still-alive')
    })

    it('fails without the guard, proving the survival case can catch the bug', async () => {
        const result = await run('unguarded')

        expect(result.code).not.toBe(0)
        expect(result.stdout).not.toContain('still-alive')
    })

    it('disarms on a rejection flood so a broken worker still surfaces as a restart', async () => {
        const result = await run('flood')

        expect(result.code).not.toBe(0)
        expect(result.stdout).not.toContain('still-alive')
    })
})
