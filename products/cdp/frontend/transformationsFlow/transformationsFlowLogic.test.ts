import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { HogFunctionType } from '~/types'

import { transformationsFlowLogic } from './transformationsFlowLogic'

const transformation = (id: string, execution_order: number, hog: string): HogFunctionType =>
    ({
        id,
        name: id,
        type: 'transformation',
        enabled: true,
        hog,
        execution_order,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        inputs: {},
        filters: {},
    }) as HogFunctionType

const ADD_TAG = transformation('add-tag', 1, 'add')
const DROP = transformation('drop', 2, 'drop')
const RENAME = transformation('rename', 3, 'rename')

describe('transformationsFlowLogic', () => {
    let logic: ReturnType<typeof transformationsFlowLogic.build>
    let invocationInputs: Record<string, any>[]

    beforeEach(async () => {
        invocationInputs = []
        const invocations = async ({ request }: { request: Request }): Promise<[number, any]> => {
            const body = await request.json()
            const event = body.globals.event
            invocationInputs.push(event)
            switch (body.configuration.hog) {
                case 'add':
                    return [
                        200,
                        {
                            status: 'success',
                            logs: [],
                            result: { ...event, properties: { ...event.properties, tag: 'added' } },
                        },
                    ]
                case 'drop':
                    return [200, { status: 'success', logs: [], result: null }]
                default:
                    return [200, { status: 'success', logs: [], result: event }]
            }
        }
        useMocks({
            get: {
                '/api/environments/:team_id/hog_functions/': { count: 3, next: null, results: [RENAME, DROP, ADD_TAG] },
                '/api/projects/:team_id/event_filter/': { mode: 'disabled' },
            },
            post: {
                '/api/environments/:team_id/hog_functions/:id/invocations': invocations,
                '/api/projects/:team_id/hog_functions/:id/invocations': invocations,
            },
        })
        initKeaTests()
        logic = transformationsFlowLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('sends the output of each transformation to the next one and stops when one drops the event', async () => {
        logic.actions.runAllTestSteps()
        await expectLogic(logic).toFinishAllListeners()

        expect(invocationInputs.map((event) => event.properties.tag)).toEqual([undefined, 'added'])
        await expectLogic(logic).toMatchValues({
            testFinished: true,
            testDroppedBy: expect.objectContaining({ id: 'drop' }),
            testResults: {
                'add-tag': expect.objectContaining({ outcome: 'changed' }),
                drop: expect.objectContaining({ outcome: 'dropped' }),
            },
        })
    })
})
