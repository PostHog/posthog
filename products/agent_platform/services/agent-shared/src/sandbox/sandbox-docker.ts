/**
 * Docker sandbox pool. Per-session container, talks JSON-RPC over a Unix
 * socket bind-mounted into the container. The container image runs a small
 * Node host that loads each tool's compiled.js and dispatches invoke calls.
 *
 * This is the stub shape — wires up child_process docker calls and the host
 * directory layout, but the actual host image must be pre-built. Tests use the
 * in-process pool; this pool is exercised by `agent-tests-v2` when Docker is
 * available locally (skipped otherwise).
 */

import { spawn } from 'child_process'
import { promises as fs } from 'fs'
import * as os from 'os'
import * as path from 'path'

import { AcquireOpts, InvokeRequest, InvokeResponse, Sandbox, SandboxPool } from './sandbox'

interface DockerSandboxState {
    sessionId: string
    containerId: string
    workDir: string
}

async function dockerAvailable(): Promise<boolean> {
    return new Promise((resolve) => {
        const p = spawn('docker', ['info'], { stdio: 'ignore' })
        p.on('exit', (code) => resolve(code === 0))
        p.on('error', () => resolve(false))
    })
}

async function runDocker(args: string[]): Promise<{ stdout: string; stderr: string; code: number }> {
    return new Promise((resolve, reject) => {
        const p = spawn('docker', args)
        let stdout = ''
        let stderr = ''
        p.stdout.on('data', (d) => (stdout += d.toString()))
        p.stderr.on('data', (d) => (stderr += d.toString()))
        p.on('exit', (code) => resolve({ stdout, stderr, code: code ?? -1 }))
        p.on('error', reject)
    })
}

class DockerSandbox implements Sandbox {
    private readonly state: DockerSandboxState
    private alive = true

    constructor(state: DockerSandboxState) {
        this.state = state
    }

    get sessionId(): string {
        return this.state.sessionId
    }

    /** Container id — `docker rm -f <containerId>` is the reaper command. */
    get providerSandboxId(): string {
        return this.state.containerId
    }

    async invoke(req: InvokeRequest): Promise<InvokeResponse> {
        if (!this.alive) {
            return { ok: false, error: { code: 'sandbox_released', message: 'released' } }
        }
        // Wire format: write req.json into workDir, invoke a docker exec that
        // tells the host to dispatch, read response.json. Kept simple — the
        // host's IPC is HTTP over UDS in the eventual impl. For now this is the
        // skeleton; agent-tests-v2 exercises it when SANDBOX_BACKEND=docker.
        try {
            const reqPath = path.join(this.state.workDir, 'request.json')
            const resPath = path.join(this.state.workDir, 'response.json')
            await fs.writeFile(reqPath, JSON.stringify(req))
            const { code, stderr } = await runDocker([
                'exec',
                this.state.containerId,
                'node',
                '/sandbox/dispatch.js',
                '/workdir/request.json',
                '/workdir/response.json',
            ])
            if (code !== 0) {
                return { ok: false, error: { code: 'exec_failed', message: stderr } }
            }
            const out = JSON.parse(await fs.readFile(resPath, 'utf-8')) as InvokeResponse
            return out
        } catch (err) {
            return { ok: false, error: { code: 'docker_invoke_failed', message: (err as Error).message } }
        }
    }

    async isAlive(): Promise<boolean> {
        if (!this.alive) {
            return false
        }
        const { code } = await runDocker(['inspect', '-f', '{{.State.Running}}', this.state.containerId])
        return code === 0
    }

    async destroy(): Promise<void> {
        this.alive = false
        await runDocker(['rm', '-f', this.state.containerId]).catch(() => undefined)
        await fs.rm(this.state.workDir, { recursive: true, force: true }).catch(() => undefined)
    }
}

export class DockerSandboxPool implements SandboxPool {
    readonly kind = 'docker' as const
    private readonly bySession = new Map<string, DockerSandbox>()
    private readonly image: string

    constructor(opts?: { image?: string }) {
        this.image = opts?.image ?? 'posthog/agent-sandbox-host:v1'
    }

    async acquireForSession(opts: AcquireOpts): Promise<Sandbox> {
        const existing = this.bySession.get(opts.sessionId)
        if (existing && (await existing.isAlive())) {
            return existing
        }
        if (!(await dockerAvailable())) {
            throw new Error('docker not available on this host')
        }
        const workDir = await fs.mkdtemp(path.join(os.tmpdir(), `sandbox-${opts.sessionId}-`))
        // Lay out compiled.js for each tool under workDir/tools/<id>/compiled.js
        for (const t of opts.tools) {
            const dir = path.join(workDir, 'tools', t.id)
            await fs.mkdir(dir, { recursive: true })
            await fs.writeFile(path.join(dir, 'compiled.js'), t.compiledJs)
            await fs.writeFile(path.join(dir, 'schema.json'), JSON.stringify(t.schemaJson))
        }
        await fs.writeFile(path.join(workDir, 'nonces.json'), JSON.stringify(opts.nonces))
        const { stdout, code, stderr } = await runDocker([
            'run',
            '-d',
            '--rm',
            // Untrusted-ish author tool code. No network (custom tools compute +
            // return; the runner egresses). Drop all caps, cap PIDs and memory
            // so a runaway / fork-bomb tool can't exhaust the host. The /workdir
            // bind mount stays writable (dispatch reads tools + writes results).
            '--network=none',
            '--cap-drop=ALL',
            '--security-opt=no-new-privileges',
            '--pids-limit=512',
            '--memory=512m',
            '-v',
            `${workDir}:/workdir`,
            this.image,
            'node',
            '/sandbox/host.js',
        ])
        if (code !== 0) {
            await fs.rm(workDir, { recursive: true, force: true }).catch(() => undefined)
            throw new Error(`docker run failed: ${stderr.trim()}`)
        }
        const containerId = stdout.trim()
        // Wait for the in-container host to drop its alive marker before
        // we hand the sandbox out. Bounded — 5s is plenty for a node:24
        // process to write a file.
        const aliveDeadline = Date.now() + 5_000
        while (Date.now() < aliveDeadline) {
            try {
                await fs.access(path.join(workDir, 'host.alive'))
                break
            } catch {
                await new Promise((r) => setTimeout(r, 50))
            }
        }
        const sandbox = new DockerSandbox({ sessionId: opts.sessionId, containerId, workDir })
        this.bySession.set(opts.sessionId, sandbox)
        return sandbox
    }

    async release(sessionId: string): Promise<void> {
        const s = this.bySession.get(sessionId)
        if (s) {
            await s.destroy()
            this.bySession.delete(sessionId)
        }
    }
}
