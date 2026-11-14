import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { PylonImportJobApi } from '../../generated/api.schemas'
import { pylonImportLogic, PylonImportJobStatus } from './pylonImportLogic'

function makeJob(status: PylonImportJobStatus, overrides: Partial<PylonImportJobApi> = {}): PylonImportJobApi {
    return {
        id: 'job-1',
        status,
        region: 'us',
        has_credentials: true,
        total_issues: 0,
        processed_issues: 0,
        imported_issues: 0,
        skipped_issues: 0,
        failed_issues: 0,
        started_at: null,
        finished_at: null,
        latest_error: null,
        created_at: '2020-01-01T00:00:00Z',
        updated_at: '2020-01-01T00:00:00Z',
        ...overrides,
    }
}

describe('pylonImportLogic', () => {
    let logic: ReturnType<typeof pylonImportLogic.build>
    let submittedBody: Record<string, unknown> | null

    beforeEach(async () => {
        silenceKeaLoadersErrors()
        jest.useFakeTimers()
        submittedBody = null
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/pylon_imports/status/': () => [
                    200,
                    makeJob('completed', { region: 'eu' }),
                ],
            },
            post: {
                '/api/projects/:team_id/conversations/pylon_imports/': async ({ request }) => {
                    submittedBody = (await request.json()) as Record<string, unknown>
                    return [201, makeJob('running', { region: 'eu' })]
                },
            },
        })
        initKeaTests()
        logic = pylonImportLogic()
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
        ['running', makeJob('running', { processed_issues: 3, total_issues: 40 }), true, '3 / 40'],
        ['pending with no total', makeJob('pending', { processed_issues: 5 }), true, '5 processed'],
        ['completed', makeJob('completed'), false, null],
    ])('exposes progress + running state for %s', async (_label, job, running, label) => {
        await expectLogic(logic, () => {
            logic.actions.loadImportJobSuccess(job)
        }).toMatchValues({ isImportRunning: running, importProgressLabel: label })
    })

    it('reloads the job after a failed start, because the server may have kept it', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/pylon_imports/status/': () => [200, makeJob('pending')],
            },
            post: {
                '/api/projects/:team_id/conversations/pylon_imports/': () => [500, { detail: 'unconfirmed' }],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.setApiToken('fake-token')
            logic.actions.submitImport()
        })
            .toDispatchActions(['submitImportFailure', 'loadImportJobSuccess'])
            .toMatchValues({ isImportRunning: true })
    })

    it('submits the token without a region and clears it after starting', async () => {
        await expectLogic(logic, () => {
            logic.actions.setApiToken('fake-token')
            logic.actions.submitImport()
        })
            .toDispatchActions(['submitImportSuccess', 'startPolling'])
            .toMatchValues({ apiToken: '' })

        expect(submittedBody).toEqual({ api_token: 'fake-token', default_email_channel_id: null })
    })
})
