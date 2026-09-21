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
if (process.argv[2] === 'guarded') {
    installUnhandledRejectionGuard(noopLogger)
}
// The rejection shape from the bug: a promise nothing awaits rejects while the
// process otherwise has work left to do.
Promise.reject(new Error('TargetCloseError: Protocol error (Runtime.evaluate): Target closed'))
setTimeout(() => {
    process.stdout.write('still-alive')
}, 50)
`

function exec(command: string, args: string[]): Promise<{ code: number; stdout: string; stderr: string }> {
    return new Promise((resolve, reject) => {
        execFile(command, args, (err, stdout, stderr) => {
            // A non-zero exit reports as err with the code attached; resolve, not reject.
            const code = (err as NodeJS.ErrnoException | null)?.code
            resolve({ code: typeof code === 'number' ? code : err ? 1 : 0, stdout: String(stdout), stderr: String(stderr) })
        })
    })
}

describe('installUnhandledRejectionGuard', () => {
    let dir: string
    let guardModule: string

    beforeAll(async () => {
        dir = await fs.mkdtemp(path.join(os.tmpdir(), 'rasterizer-guard-'))
        const tsc = path.resolve(__dirname, '../../../../node_modules/typescript/bin/tsc')
        // The guard module has no ~ imports so plain tsc compiles it without the workspace config.
        await exec('node', [
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
        guardModule = path.join(dir, 'install-unhandled-rejection-guard.js')
        await fs.writeFile(path.join(dir, 'fixture.js'), FIXTURE_SCRIPT)
    })

    afterAll(async () => {
        await fs.rm(dir, { recursive: true, force: true })
    })

    it('keeps the process alive when a promise nothing awaits rejects', async () => {
        const result = await exec('node', [path.join(dir, 'fixture.js'), 'guarded'])

        expect(result.code).toBe(0)
        expect(result.stdout).toContain('still-alive')
    })

    it('fails without the guard, proving the survival case can catch the bug', async () => {
        const result = await exec('node', [path.join(dir, 'fixture.js'), 'unguarded'])

        expect(result.code).not.toBe(0)
        expect(result.stdout).not.toContain('still-alive')
    })
})
