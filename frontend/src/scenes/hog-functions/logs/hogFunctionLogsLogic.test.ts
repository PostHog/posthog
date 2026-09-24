import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { hogFunctionLogsLogic } from './hogFunctionLogsLogic'
import { GroupedLogEntry, logsViewerLogic } from './logsViewerLogic'

const EVENT_ID = '00000000-0000-0000-0000-0000000000ev'
const INSTANCE_ID = 'instance-1'

const groupedLogEntry = (): GroupedLogEntry => {
    const timestamp = dayjs.tz('2024-01-15 10:30:45.123', 'UTC')
    return {
        instanceId: INSTANCE_ID,
        maxTimestamp: timestamp,
        maxRawTimestamp: '2024-01-15 10:30:45.123',
        minTimestamp: timestamp,
        minRawTimestamp: '2024-01-15 10:30:45.123',
        logLevel: 'INFO',
        entries: [
            {
                instanceId: INSTANCE_ID,
                timestamp,
                rawTimestamp: '2024-01-15 10:30:45.123',
                level: 'INFO',
                message: `Function completed. Event: ${EVENT_ID}`,
            },
        ],
    }
}

describe('hogFunctionLogsLogic', () => {
    let logic: ReturnType<typeof hogFunctionLogsLogic.build>
    let viewerLogic: ReturnType<typeof logsViewerLogic.build>
    let invocationResponse: { status: string; logs: { timestamp: string; level: string; message: string }[] }

    beforeEach(async () => {
        invocationResponse = { status: 'success', logs: [] }
        useMocks({
            post: {
                '/api/environments/:team_id/query/HogQLQuery/': async ({ request }) => {
                    const body = (await request.json()) as { query?: { query?: string } }
                    if (!body.query?.query?.includes('FROM events')) {
                        return [200, { results: [] }]
                    }
                    return [
                        200,
                        {
                            results: [
                                [
                                    EVENT_ID,
                                    'distinct-1',
                                    '$pageview',
                                    '2024-01-15T10:30:45Z',
                                    {},
                                    '',
                                    'person-1',
                                    {},
                                    '2024-01-01T00:00:00Z',
                                ],
                            ],
                        },
                    ]
                },
                '/api/projects/:team_id/hog_functions/:id/invocations': () => [200, invocationResponse],
            },
        })
        initKeaTests()
        const props = { sourceType: 'hog_function' as const, sourceId: 'fn-1' }
        viewerLogic = logsViewerLogic(props)
        viewerLogic.mount()
        logic = hogFunctionLogsLogic(props)
        logic.mount()
        // The viewer loads on mount and replaces `groupedLogs`, so seed the group after it settles.
        await expectLogic(viewerLogic).toFinishAllListeners()
        await expectLogic(viewerLogic, () => {
            viewerLogic.actions.addLogGroups([groupedLogEntry()])
        }).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        viewerLogic.unmount()
    })

    // A retry the worker refused to run used to land as 'success', which told a user debugging a
    // destination that the retry had been delivered.
    it.each([
        ['success', 'success'],
        ['skipped', 'skipped'],
        ['error', 'failure'],
    ])('records a %s retry response as %s', async (status, expected) => {
        invocationResponse = { status, logs: [] }

        await expectLogic(logic, () => {
            logic.actions.retryInvocations([groupedLogEntry()])
        }).toFinishAllListeners()

        expect(logic.values.retries[INSTANCE_ID]).toBe(expected)
    })

    it('explains a skipped retry in the log entries', async () => {
        invocationResponse = { status: 'skipped', logs: [] }

        await expectLogic(logic, () => {
            logic.actions.retryInvocations([groupedLogEntry()])
        }).toFinishAllListeners()

        const entries = viewerLogic.values.groupedLogs.find((x) => x.instanceId === INSTANCE_ID)?.entries ?? []
        expect(entries.some((x) => x.level === 'WARN' && x.message.includes('did not match the filters'))).toBe(true)
    })
})
