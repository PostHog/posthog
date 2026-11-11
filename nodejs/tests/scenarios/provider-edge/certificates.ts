import { execFile } from 'child_process'
import { mkdirSync, readFileSync, writeFileSync } from 'fs'
import path from 'path'
import { promisify } from 'util'

const run = promisify(execFile)

const VALID_DAYS = '30'

export type Leaf = { key: Buffer; cert: Buffer }

export type Certificates = { caCertPath: string; leaves: Map<string, Leaf> }

async function openssl(args: string[]): Promise<void> {
    try {
        await run('openssl', args)
    } catch (error) {
        const { stderr, message } = error as { stderr?: string; message: string }
        throw new Error(`openssl ${args[0]} failed: ${stderr?.trim() || message}`)
    }
}

export async function createCertificates(caDir: string, hosts: string[]): Promise<Certificates> {
    mkdirSync(caDir, { recursive: true })
    const file = (name: string): string => path.join(caDir, name)
    const caCertPath = file('ca.pem')
    await openssl([
        'req',
        '-x509',
        '-newkey',
        'rsa:2048',
        '-nodes',
        '-keyout',
        file('ca.key'),
        '-out',
        caCertPath,
        '-days',
        VALID_DAYS,
        '-subj',
        '/CN=Scenario provider edge CA',
        '-addext',
        'basicConstraints=critical,CA:TRUE',
        '-addext',
        'keyUsage=critical,keyCertSign,cRLSign',
    ])
    const leaves = new Map<string, Leaf>()
    for (const host of hosts) {
        writeFileSync(file(`${host}.ext`), `subjectAltName=DNS:${host}\nextendedKeyUsage=serverAuth\n`)
        await openssl([
            'req',
            '-newkey',
            'rsa:2048',
            '-nodes',
            '-keyout',
            file(`${host}.key`),
            '-out',
            file(`${host}.csr`),
            '-subj',
            `/CN=${host}`,
        ])
        await openssl([
            'x509',
            '-req',
            '-in',
            file(`${host}.csr`),
            '-CA',
            caCertPath,
            '-CAkey',
            file('ca.key'),
            '-set_serial',
            String(leaves.size + 1),
            '-days',
            VALID_DAYS,
            '-extfile',
            file(`${host}.ext`),
            '-out',
            file(`${host}.pem`),
        ])
        leaves.set(host, { key: readFileSync(file(`${host}.key`)), cert: readFileSync(file(`${host}.pem`)) })
    }
    return { caCertPath, leaves }
}
