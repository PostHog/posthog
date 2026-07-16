import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { PlainImportJobApi } from '../../generated/api.schemas'
import { plainImportLogic, PlainImportJobStatus } from './plainImportLogic'

function makeJob(status: PlainImportJobStatus, overrides: Partial<PlainImportJobApi> = {}): PlainImportJobApi {
    return {
        id: 'job-1',
        status,
        region: null,
        has_credentials: false,
        total_tickets: 0,
        processed_tickets: 0,
        imported_tickets: 0,
        skipped_tickets: 0,
        failed_tickets: 0,
        started_at: null,
        finished_at: null,
        latest_error: null,
        created_at: '2020-01-01T00:00:00Z',
        updated_at: '2020-01-01T00:00:00Z',
        ...overrides,
    }
}

describe('plainImportLogic', () => {
    let logic: ReturnType<typeof plainImportLogic.build>

    beforeEach(async () => {
        silenceKeaLoadersErrors()
        jest.useFakeTimers()
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/plain_imports/status/': () => [404, {}],
            },
            post: {
                '/api/projects/:team_id/conversations/plain_imports/': () => [201, makeJob('running')],
            },
        })
        initKeaTests()
        logic = plainImportLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadImportJobSuccess'])
    })

    afterEach(() => {
        logic?.unmount()
        jest.clearAllTimers()
        jest.useRealTimers()
        resumeKeaLoadersErrors()
    })

    it.each([
        ['running', makeJob('running', { processed_tickets: 3, total_tickets: 40 }), true, '3 / 40'],
        ['pending with no total', makeJob('pending', { processed_tickets: 5 }), true, '5 processed'],
        ['completed', makeJob('completed'), false, null],
        ['failed', makeJob('failed'), false, null],
    ])('exposes progress + running state for %s', async (_label, job, running, label) => {
        await expectLogic(logic, () => {
            logic.actions.loadImportJobSuccess(job)
        }).toMatchValues({
            isImportRunning: running,
            importProgressLabel: label,
        })
    })

    it('starts polling and clears the API key on a successful submit', async () => {
        await expectLogic(logic, () => {
            logic.actions.submitImportSuccess(makeJob('running'))
        })
            .toDispatchActions(['setApiKey', 'startPolling'])
            .toMatchValues({ apiKey: '' })
    })

    it('stops polling once the job reaches a terminal status', async () => {
        await expectLogic(logic, () => {
            logic.actions.startPolling()
        }).toDispatchActions(['startPolling'])

        await expectLogic(logic, () => {
            logic.actions.loadImportJobSuccess(makeJob('completed'))
        }).toDispatchActions(['stopPolling'])
    })

    it('starts polling when a running job is observed and no timer is active', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadImportJobSuccess(makeJob('running'))
        }).toDispatchActions(['startPolling'])
    })
})
