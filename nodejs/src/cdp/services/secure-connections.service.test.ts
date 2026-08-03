import jwt from 'jsonwebtoken'
import { randomBytes } from 'node:crypto'
import http from 'node:http'
import net from 'node:net'

import { PostgresRouter } from '~/common/utils/db/postgres'

import { SecureConnectionsService, magicHostnameForConnection } from './secure-connections.service'

const CONNECTION_ID = 'fd247df6-cf23-4abc-8ee0-3bce4bbc5be0'
const WORKLOAD_SECRET = randomBytes(32).toString('hex')

function listen(server: net.Server): Promise<number> {
    return new Promise((resolve) =>
        server.listen(0, '127.0.0.1', () => resolve((server.address() as net.AddressInfo).port))
    )
}

describe('SecureConnectionsService', () => {
    const servers: net.Server[] = []

    afterEach(async () => {
        await Promise.all(
            servers.splice(0).map((server) => new Promise<void>((resolve) => server.close(() => resolve())))
        )
    })

    function postgresWithApprovals(approvals: Record<string, object>): PostgresRouter {
        return {
            query: jest.fn().mockResolvedValue({ rows: [{ cdp_approved_connections: approvals }] }),
        } as unknown as PostgresRouter
    }

    it('rejects a magic hostname before contacting the worker when CDP approval is absent', async () => {
        const postgres = postgresWithApprovals({})
        const service = new SecureConnectionsService(postgres, {
            workerUrl: 'http://127.0.0.1:1',
            workloadSecret: WORKLOAD_SECRET,
        })

        await expect(service.fetch(42, `http://${magicHostnameForConnection(CONNECTION_ID)}/`, {})).rejects.toThrow(
            'is not approved for CDP'
        )
        expect(postgres.query).toHaveBeenCalledWith(
            expect.anything(),
            expect.stringContaining("extra_settings -> 'secure_connections'"),
            [42],
            'secure-connections-cdp-approval'
        )
    })

    it('does not allow an approval for a different connection or team to authorize the request', async () => {
        const otherConnectionId = '36c67676-7051-4ef9-8d77-e6a1ad98037d'
        const postgres = postgresWithApprovals({
            [otherConnectionId]: { name: 'other', selector_kind: 'hostname', selector: 'other.internal' },
        })
        const service = new SecureConnectionsService(postgres, {
            workerUrl: 'http://127.0.0.1:1',
            workloadSecret: WORKLOAD_SECRET,
        })

        await expect(service.fetch(99, `http://${magicHostnameForConnection(CONNECTION_ID)}/`, {})).rejects.toThrow(
            'is not approved for CDP'
        )
        expect(postgres.query).toHaveBeenCalledWith(expect.anything(), expect.any(String), [99], expect.any(String))
    })

    it('rejects HTTPS explicitly until port-routed TLS metadata is supported', async () => {
        const postgres = postgresWithApprovals({
            [CONNECTION_ID]: { name: 'api', selector_kind: 'hostname', selector: 'api.acme.internal' },
        })
        const service = new SecureConnectionsService(postgres, {
            workerUrl: 'http://127.0.0.1:1',
            workloadSecret: WORKLOAD_SECRET,
        })

        await expect(service.fetch(42, `https://${magicHostnameForConnection(CONNECTION_ID)}/`, {})).rejects.toThrow(
            'currently supports HTTP services'
        )
        expect(postgres.query).not.toHaveBeenCalled()
    })

    it('rejects malformed routing metadata loaded from the database', async () => {
        const postgres = postgresWithApprovals({
            [CONNECTION_ID]: { name: 'api', selector_kind: 'hostname', selector: 'api.internal\r\ninjected: yes' },
        })
        const service = new SecureConnectionsService(postgres, {
            workerUrl: 'http://127.0.0.1:1',
            workloadSecret: WORKLOAD_SECRET,
        })

        await expect(service.fetch(42, `http://${magicHostnameForConnection(CONNECTION_ID)}/`, {})).rejects.toThrow(
            'invalid CDP routing metadata'
        )
    })

    it('surfaces a worker CONNECT rejection without sending application bytes', async () => {
        let connects = 0
        const worker = http.createServer()
        worker.on('connect', (_request, socket) => {
            connects++
            socket.end('HTTP/1.1 404 Not Found\r\n\r\n')
        })
        servers.push(worker)
        const workerPort = await listen(worker)
        const postgres = postgresWithApprovals({
            [CONNECTION_ID]: { name: 'api', selector_kind: 'hostname', selector: 'api.acme.internal' },
        })
        const service = new SecureConnectionsService(postgres, {
            workerUrl: `http://127.0.0.1:${workerPort}`,
            workloadSecret: WORKLOAD_SECRET,
        })

        await expect(service.fetch(42, `http://${magicHostnameForConnection(CONNECTION_ID)}/`, {})).rejects.toThrow(
            'worker rejected the tunnel (404)'
        )
        expect(connects).toBe(1)
    })

    it('opens an authenticated CONNECT tunnel and sends HTTP bytes to the approved service', async () => {
        const upstream = http.createServer((request, response) => {
            response.setHeader('content-type', 'application/json')
            response.end(JSON.stringify({ host: request.headers.host, path: request.url }))
        })
        servers.push(upstream)
        const upstreamPort = await listen(upstream)

        let connectPath: string | undefined
        let grantPayload: jwt.JwtPayload | string | undefined
        const worker = http.createServer()
        worker.on('connect', (request, clientSocket) => {
            connectPath = request.url
            const grant = request.headers.authorization?.replace('Bearer ', '') ?? ''
            grantPayload = jwt.verify(grant, WORKLOAD_SECRET, { audience: 'burrow-worker' })
            const upstreamSocket = net.connect(upstreamPort, '127.0.0.1', () => {
                clientSocket.write('HTTP/1.1 200 Connection Established\r\n\r\n')
                clientSocket.pipe(upstreamSocket).pipe(clientSocket)
            })
        })
        servers.push(worker)
        const workerPort = await listen(worker)

        const postgres = postgresWithApprovals({
            [CONNECTION_ID]: { name: 'api', selector_kind: 'hostname', selector: 'api.acme.internal' },
        })
        const service = new SecureConnectionsService(postgres, {
            workerUrl: `http://127.0.0.1:${workerPort}`,
            workloadSecret: WORKLOAD_SECRET,
        })

        const response = await service.fetch(42, `http://${magicHostnameForConnection(CONNECTION_ID)}/orders?limit=2`, {
            method: 'GET',
        })

        expect(response.status).toBe(200)
        await expect(response.json()).resolves.toEqual({ host: 'api.acme.internal', path: '/orders?limit=2' })
        expect(connectPath).toBe(`/v1/connections/${CONNECTION_ID}`)
        expect(grantPayload).toEqual(
            expect.objectContaining({
                sub: 'cdp-cyclotron-worker',
                team_id: '42',
                connection_id: CONNECTION_ID,
                scopes: ['forward'],
            })
        )
    })
})
