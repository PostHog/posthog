import { installMockEventSource, MockEventSource } from 'lib/wizard-sync/eventSource.mock'

import { expectLogic } from 'kea-test-utils'

import { projectLogic } from 'scenes/projectLogic'

import { initKeaTests } from '~/test/init'

import { installationProgressLogic, resetWizardSyncTelemetryForTests } from './installationProgressLogic'

jest.mock('products/wizard/frontend/generated/api', () => ({
    wizardSessionsLatestRetrieve: jest.fn(),
    getWizardSessionsStreamRetrieveUrl: jest.fn(() => '/mock-session-stream-url'),
}))

jest.mock('products/tasks/frontend/generated/api', () => ({
    getTasksRunsStreamRetrieveUrl: jest.fn(() => '/mock-run-stream-url'),
    tasksRunsRetrieve: jest.fn(),
    tasksActiveWizardRunRetrieve: jest.fn(),
    tasksRunsCancelCreate: jest.fn(),
}))

describe('installationProgressLogic session transport sharing', () => {
    let restoreEventSource: () => void
    let mounted: ReturnType<typeof installationProgressLogic.build>[]

    beforeEach(async () => {
        initKeaTests()
        resetWizardSyncTelemetryForTests()
        restoreEventSource = installMockEventSource()
        mounted = []
        projectLogic.mount()
        // A connect without a project errors out instead of opening anything — wait for the test
        // bootstrap to provide one before mounting the instances under test.
        await expectLogic(projectLogic).toMatchValues({ currentProjectId: expect.any(Number) })
    })

    afterEach(() => {
        mounted.reverse().forEach((logic) => logic.unmount())
        restoreEventSource()
    })

    function mountCloudInstance(runId: string): void {
        const logic = installationProgressLogic({ mode: 'cloud', runId, taskId: 'task-1' })
        logic.mount()
        mounted.push(logic)
    }

    // `connectSession` rebuilds the transport rather than being idempotent, so an unrefcounted
    // connect made every mount drop a running poll loop and restart it with its backoff cleared —
    // which is how a stuck client keeps hitting the endpoint at full cadence.
    it('opens the session transport once however many instances share it', () => {
        mountCloudInstance('run-1')
        expect(MockEventSource.instances).toHaveLength(1)

        mountCloudInstance('run-2')
        expect(MockEventSource.instances).toHaveLength(1)
    })
})
