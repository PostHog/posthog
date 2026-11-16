import { RoleSpec, roleSpecs, secretsOf } from './roles'
import { groupNamesOf, groupsOf, hostsOf, missingTargets, nodesOf, scenarioGroupsOf, topologyOf } from './topology'

const LIST = `BROKER  GROUP                     STATE
0       orders-consumer           Stable
0       billing-audit             Empty
`

// Invented from rpk's layout: padded columns, a blank member and client on an unassigned
// partition, and a group whose only member is a process the runner did not start.
const described = (lag: string): string => `GROUP        orders-consumer
COORDINATOR  0
STATE        Stable
BALANCER     range
MEMBERS      2
TOTAL-LAG    7

TOPIC        PARTITION  CURRENT-OFFSET  LOG-START-OFFSET  LOG-END-OFFSET  LAG   MEMBER-ID       CLIENT-ID                        HOST
orders_in    0          10              0                 15              ${lag.padEnd(4)}  m-1             scenario-cdp-processed-events    127.0.0.1
orders_in    1          -               0                 0               -                                                       
orders_in    2          4               0                 6               2     m-2             scenario-cdp-processed-events    127.0.0.1

GROUP        billing-audit
COORDINATOR  0
STATE        Stable
BALANCER     range
MEMBERS      1
TOTAL-LAG    0

TOPIC          PARTITION  CURRENT-OFFSET  LOG-START-OFFSET  LOG-END-OFFSET  LAG   MEMBER-ID  CLIENT-ID      HOST
billing_audit  0          3               0                 3               0     m-9        audit-sidecar  10.0.0.2
`

const SPECS: RoleSpec[] = roleSpecs({}, { url: 'http://edge' }, secretsOf({}), '/state', {}, undefined, {
    'cdp-cyclotron-worker-email': 2,
})

const CLIENTS = [
    { application: 'scenario-cdp-cyclotron-worker-email', database: 'cyclotron', connections: 4 },
    { application: 'scenario-cdp-api', database: 'posthog', connections: 2 },
    { application: 'psql', database: 'posthog', connections: 1 },
]

const topologyFrom = (lag: string, clients = CLIENTS, adapter = 'workflows'): ReturnType<typeof topologyOf> =>
    topologyOf({ adapter, specs: SPECS, groups: groupsOf(described(lag)), clients, recordedAt: new Date(0) })

describe('topology', () => {
    it('reads which role consumes which group and topic, and which database it talks to', () => {
        expect(groupNamesOf(LIST)).toEqual(['orders-consumer', 'billing-audit'])
        expect(scenarioGroupsOf(groupsOf(described('5')))).toEqual([
            { group: 'orders-consumer', topics: ['orders_in'] },
        ])

        const topology = topologyFrom('5')

        expect(topology).toMatchObject({
            consumers: [
                {
                    adapter: 'workflows',
                    role: 'cdp-processed-events',
                    group: 'orders-consumer',
                    topics: ['orders_in'],
                    lag: 7,
                },
            ],
            databases: [
                { adapter: 'workflows', role: 'cdp-api', database: 'posthog', connections: 2 },
                { adapter: 'workflows', role: 'cdp-cyclotron-worker-email', database: 'cyclotron', connections: 4 },
            ],
            hosts: [],
        })
        expect(topology.processes).toContainEqual({
            adapter: 'workflows',
            role: 'cdp-cyclotron-worker-email',
            replicas: 2,
        })
    })

    it('keeps its hash across lag and connection counts and changes it with the wiring or the adapter', () => {
        const hash = topologyFrom('5').hash

        expect(
            topologyFrom(
                '500',
                CLIENTS.map((client) => ({ ...client, connections: 9 }))
            ).hash
        ).toEqual(hash)
        expect(topologyFrom('5', CLIENTS.slice(1)).hash).not.toEqual(hash)
        expect(topologyFrom('5', CLIENTS, 'another-adapter').hash).not.toEqual(hash)
    })

    it('counts the requests the edge answered per host and names the nodes a valve can target', () => {
        const topology = topologyFrom('5')
        const at = new Date(0).toISOString()

        expect(
            hostsOf([
                { seq: 1, at, kind: 'ses.send', status: 200, detail: {} },
                {
                    seq: 2,
                    at,
                    kind: 'webhook',
                    status: 500,
                    detail: { request: { method: 'POST', host: 'hooks.example.com', path: '/' } },
                },
                { seq: 3, at, kind: 'ses.feedback', status: 200, detail: {} },
                { seq: 4, at, kind: 'ses.send', status: 200, detail: {} },
            ])
        ).toEqual([
            { host: 'hooks.example.com', requests: 1 },
            { host: 'ses', requests: 2 },
        ])
        expect(missingTargets(['postgres', 'ses', 'cdp-api', 'redis', 'redis'], nodesOf(topology, ['ses']))).toEqual([
            'redis',
        ])
        expect(missingTargets(['cyclotron'], nodesOf(topologyFrom('5', CLIENTS.slice(1)), []))).toEqual(['cyclotron'])
        expect(nodesOf(topologyFrom('5', []), [])).not.toContain('postgres')
    })
})
