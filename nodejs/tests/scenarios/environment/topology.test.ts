import { chmodSync, mkdtempSync, rmSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'

import { RoleSpec, roleSpecs, secretsOf } from './roles'
import { groupLag } from './stack'
import { KafkaGroup, kafkaGroups, scenarioGroupsOf, wiringOf } from './topology'

const LIST = `BROKER  GROUP                     STATE
0       orders-consumer           Stable
0       billing-audit             Empty
`

const described = (lag: string): string => `GROUP        orders-consumer
COORDINATOR  0
STATE        Stable
BALANCER     range
MEMBERS      3
TOTAL-LAG    7

TOPIC        PARTITION  CURRENT-OFFSET  LOG-START-OFFSET  LOG-END-OFFSET  LAG   MEMBER-ID       CLIENT-ID                        HOST
orders_in    0          10              0                 15              ${lag.padEnd(4)}  m-1             scenario-cdp-processed-events    127.0.0.1
orders_in    1          -               0                 0               -
orders_in    2          4               0                 6               2     m-2             scenario-cdp-processed-events    127.0.0.1
orders_in    3          -               0                 9                     m-4             scenario-cdp-ses-webhooks        127.0.0.1
orders_in    4          1               0                 41              40    m-3             scenario-cdp-api                 127.0.0.1

GROUP        billing-audit
COORDINATOR  0
STATE        Stable
BALANCER     range
MEMBERS      1
TOTAL-LAG    0

TOPIC          PARTITION  CURRENT-OFFSET  LOG-START-OFFSET  LOG-END-OFFSET  LAG   MEMBER-ID  CLIENT-ID      HOST
billing_audit  0          3               0                 3               0     m-9        audit-sidecar  10.0.0.2
`

function fakeDocker(dir: string, output: { list: string; describe: string; exitCode?: number }): string {
    writeFileSync(path.join(dir, 'list.txt'), output.list)
    writeFileSync(path.join(dir, 'describe.txt'), output.describe)
    const docker = path.join(dir, 'docker')
    writeFileSync(
        docker,
        [
            '#!/bin/sh',
            `[ "$5" = list ] && cat '${path.join(dir, 'list.txt')}'`,
            `[ "$5" = describe ] && cat '${path.join(dir, 'describe.txt')}'`,
            `exit ${output.exitCode ?? 0}`,
        ].join('\n')
    )
    chmodSync(docker, 0o755)
    return docker
}

const SPECS: RoleSpec[] = roleSpecs({}, { url: 'http://edge' }, secretsOf({}), '/state', {}, undefined, {
    'cdp-cyclotron-worker-email': 2,
})

const CLIENTS = [
    { application: 'scenario-cdp-cyclotron-worker-email', database: 'cyclotron', connections: 4 },
    { application: 'scenario-cdp-api', database: 'posthog', connections: 2 },
    { application: 'psql', database: 'posthog', connections: 1 },
]

const wiringFrom = (groups: KafkaGroup[], clients = CLIENTS, adapter = 'workflows'): ReturnType<typeof wiringOf> =>
    wiringOf({ adapter, specs: SPECS, groups, clients, recordedAt: new Date(0) })

describe('topology', () => {
    let dir: string
    const groupsWithLag = (lag: string): Promise<KafkaGroup[]> =>
        kafkaGroups(fakeDocker(dir, { list: LIST, describe: described(lag) }))

    beforeEach(() => {
        dir = mkdtempSync(path.join(os.tmpdir(), 'scenario-topology-'))
    })

    afterEach(() => {
        rmSync(dir, { recursive: true, force: true })
    })

    it('reads which role consumes which group and topic with the lag of its own partitions, and which database it talks to', async () => {
        const groups = await groupsWithLag('5')

        expect(scenarioGroupsOf(groups)).toEqual([{ group: 'orders-consumer', topics: ['orders_in'] }])
        expect(wiringFrom(groups)).toMatchObject({
            consumers: [
                { adapter: 'workflows', role: 'cdp-api', group: 'orders-consumer', topics: ['orders_in'], lag: 40 },
                {
                    adapter: 'workflows',
                    role: 'cdp-processed-events',
                    group: 'orders-consumer',
                    topics: ['orders_in'],
                    lag: 7,
                },
                {
                    adapter: 'workflows',
                    role: 'cdp-ses-webhooks',
                    group: 'orders-consumer',
                    topics: ['orders_in'],
                    lag: null,
                },
            ],
            databases: [
                { adapter: 'workflows', role: 'cdp-api', database: 'posthog', connections: 2 },
                { adapter: 'workflows', role: 'cdp-cyclotron-worker-email', database: 'cyclotron', connections: 4 },
            ],
        })
        expect(wiringFrom(groups).processes).toContainEqual({
            adapter: 'workflows',
            role: 'cdp-cyclotron-worker-email',
            replicas: 2,
        })
    })

    it('keeps its hash across lag, connection counts, a server read twice and a pooled session another role used last, and changes it with the wiring or the adapter', async () => {
        const groups = await groupsWithLag('5')
        const hash = wiringFrom(groups).hash

        expect(
            wiringFrom(
                await groupsWithLag('500'),
                CLIENTS.map((client) => ({ ...client, connections: 9 }))
            ).hash
        ).toEqual(hash)
        expect(wiringFrom(groups, [...CLIENTS, CLIENTS[0]]).hash).toEqual(hash)
        expect(
            wiringFrom(groups, [{ ...CLIENTS[0], application: 'scenario-cdp-api' }, ...CLIENTS.slice(1)]).hash
        ).toEqual(hash)
        expect(wiringFrom(groups, CLIENTS.slice(1)).hash).not.toEqual(hash)
        expect(wiringFrom(groups, CLIENTS, 'another-adapter').hash).not.toEqual(hash)
    })

    it('reads every group of a broker whose descriptions together pass the output limit of one call', async () => {
        const names = Array.from({ length: 2000 }, (_, index) => `group-${index}`)
        writeFileSync(
            path.join(dir, 'list.txt'),
            ['BROKER  GROUP  STATE', ...names.map((name) => `0  ${name}  Empty`)].join('\n')
        )
        const docker = path.join(dir, 'docker')
        writeFileSync(
            docker,
            [
                '#!/bin/sh',
                `[ "$5" = list ] && cat '${path.join(dir, 'list.txt')}' && exit 0`,
                'shift 5',
                `for group in "$@"; do printf 'GROUP        %s\\nSTATE        Empty\\n\\nTOPIC  PARTITION  LAG  CLIENT-ID\\n%s  0  0  %0600d\\n\\n' "$group" "$group" 0; done`,
            ].join('\n')
        )
        chmodSync(docker, 0o755)

        const groups = await kafkaGroups(docker)

        expect(groups.map(({ group }) => group)).toEqual(names)
    })

    it('stops reading groups when its signal aborts, instead of waiting for rpk', async () => {
        const docker = path.join(dir, 'docker')
        writeFileSync(docker, '#!/bin/sh\nexec sleep 30\n')
        chmodSync(docker, 0o755)

        await expect(kafkaGroups(docker, AbortSignal.timeout(100))).rejects.toThrow()
    }, 2_000)

    it('fails the read when rpk fails, instead of reading its error as groups', async () => {
        await expect(
            kafkaGroups(fakeDocker(dir, { list: 'unable to dial: connection refused', describe: '', exitCode: 1 }))
        ).rejects.toThrow()
    })

    it('fails the lag read when rpk fails after it printed a zero total', async () => {
        const describe = 'GROUP        cdp-intake-transactional-email-consumer\nMEMBERS      1\nTOTAL-LAG    0\n'

        await expect(
            groupLag('cdp-intake-transactional-email-consumer', fakeDocker(dir, { list: '', describe, exitCode: 1 }))
        ).rejects.toThrow()
    })
})
