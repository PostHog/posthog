import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { IntercomImportJobApi } from '../../generated/api.schemas'
import { intercomImportLogic, IntercomImportJobStatus } from './intercomImportLogic'

function makeJob(status: IntercomImportJobStatus, overrides: Partial<IntercomImportJobApi> = {}): IntercomImportJobApi {
    return {
        id: 'job-1',
        status,
        region: 'us',
        has_credentials: true,
        total_conversations: 0,
        processed_conversations: 0,
        imported_conversations: 0,
        skipped_conversations: 0,
        failed_conversations: 0,
        started_at: null,
        finished_at: null,
        latest_error: null,
        created_at: '2020-01-01T00:00:00Z',
        updated_at: '2020-01-01T00:00:00Z',
        ...overrides,
    }
}

describe('intercomImportLogic', () => {
    let logic: ReturnType<typeof intercomImportLogic.build>
    let submittedBody: Record<string, unknown> | null

    beforeEach(async () => {
        silenceKeaLoadersErrors()
        jest.useFakeTimers()
        submittedBody = null
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/intercom_imports/status/': () => [
                    200,
                    makeJob('completed', { region: 'eu' }),
                ],
            },
            post: {
                '/api/projects/:team_id/conversations/intercom_imports/': async ({ request }) => {
                    submittedBody = (await request.json()) as Record<string, unknown>
                    return [201, makeJob('running', { region: 'eu' })]
                },
            },
        })
        initKeaTests()
        logic = intercomImportLogic()
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
        ['running', makeJob('running', { processed_conversations: 3, total_conversations: 40 }), true, '3 / 40'],
        ['pending with no total', makeJob('pending', { processed_conversations: 5 }), true, '5 processed'],
        ['completed', makeJob('completed'), false, null],
    ])('exposes progress + running state for %s', async (_label, job, running, label) => {
        await expectLogic(logic, () => {
            logic.actions.loadImportJobSuccess(job)
        }).toMatchValues({ isImportRunning: running, importProgressLabel: label })
    })

    it('submits the prefilled region and clears the token after starting', async () => {
        await expectLogic(logic, () => {
            logic.actions.setAccessToken('fake-token')
            logic.actions.submitImport()
        })
            .toDispatchActions(['submitImportSuccess', 'startPolling'])
            .toMatchValues({ accessToken: '' })

        expect(submittedBody).toEqual({ region: 'eu', access_token: 'fake-token', default_email_channel_id: null })
    })
})
