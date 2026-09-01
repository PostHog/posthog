import { execFile } from 'node:child_process'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { promisify } from 'node:util'

const execFileAsync = promisify(execFile)

export type TestTlsIdentity = {
    privateKey: Buffer
    certificate: Buffer
    cleanup: () => Promise<void>
}

export async function createTestTlsIdentity(hostname: string): Promise<TestTlsIdentity> {
    const directory = await mkdtemp(path.join(os.tmpdir(), 'posthog-test-tls-'))
    const privateKeyPath = path.join(directory, 'server.key')
    const certificatePath = path.join(directory, 'server.crt')

    try {
        await execFileAsync('openssl', [
            'req',
            '-x509',
            '-newkey',
            'ec',
            '-pkeyopt',
            'ec_paramgen_curve:P-256',
            '-nodes',
            '-keyout',
            privateKeyPath,
            '-out',
            certificatePath,
            '-days',
            '1',
            '-subj',
            `/CN=${hostname}`,
            '-addext',
            `subjectAltName=DNS:${hostname}`,
        ])
        const [privateKey, certificate] = await Promise.all([readFile(privateKeyPath), readFile(certificatePath)])

        return {
            privateKey,
            certificate,
            cleanup: async () => await rm(directory, { recursive: true, force: true }),
        }
    } catch (error) {
        await rm(directory, { recursive: true, force: true })
        throw error
    }
}
