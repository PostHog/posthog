import { execFile } from 'child_process'
import { mkdirSync, readFileSync } from 'fs'
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
        await openssl([
            'req',
            '-x509',
            '-newkey',
            'rsa:2048',
            '-nodes',
            '-keyout',
            file(`${host}.key`),
            '-out',
            file(`${host}.pem`),
            '-days',
            VALID_DAYS,
            '-subj',
            `/CN=${host}`,
            '-CA',
            caCertPath,
            '-CAkey',
            file('ca.key'),
            '-addext',
            `subjectAltName=DNS:${host}`,
            '-addext',
            'extendedKeyUsage=serverAuth',
            '-addext',
            'basicConstraints=critical,CA:FALSE',
        ])
        leaves.set(host, { key: readFileSync(file(`${host}.key`)), cert: readFileSync(file(`${host}.pem`)) })
    }
    return { caCertPath, leaves }
}
