import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { errorTrackingGitProviderFileLinksSourceFileRetrieve } from 'products/error_tracking/frontend/generated/api'

import { frameSourceFileLogic } from './frameSourceFileLogic'

jest.mock('products/error_tracking/frontend/generated/api', () => ({
    errorTrackingGitProviderFileLinksSourceFileRetrieve: jest.fn(),
}))

const readSourceFile = errorTrackingGitProviderFileLinksSourceFileRetrieve as jest.Mock

const TARGET = { eventUuid: 'event-1', eventTimestamp: '2026-01-01T00:00:00Z', rawId: 'frame-1/0' }

describe('frameSourceFileLogic', () => {
    beforeEach(() => {
        initKeaTests()
        readSourceFile.mockReset()
    })

    it('shows more of the file on each scroll to an edge', async () => {
        readSourceFile.mockResolvedValue({
            repo_path: 'services/api/app/one.py',
            commit: '0123456789abcdef0123456789abcdef01234567',
            line: 150,
            lines: Array.from({ length: 300 }, (_, i) => `line ${i + 1}`),
        })
        const logic = frameSourceFileLogic({ ...TARGET, capturedLine: 'line 150' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(readSourceFile.mock.calls[0][1]).toEqual({
            event_uuid: 'event-1',
            event_timestamp: '2026-01-01T00:00:00Z',
            frame_raw_id: 'frame-1/0',
        })
        expect(logic.values.capturedCodeCheck).toBe('matches')
        expect(logic.values.fileWindow?.context.before[0].number).toBe(135)

        logic.actions.showMoreAbove()
        logic.actions.showMoreBelow()

        expect(logic.values.fileWindow?.context.before[0].number).toBe(35)
        expect(logic.values.fileWindow?.context.after.at(-1)?.number).toBe(265)
    })

    it('keeps the captured context when the file cannot be read', async () => {
        readSourceFile.mockRejectedValue({ status: 404, detail: 'no_repo_path' })
        const logic = frameSourceFileLogic({ ...TARGET, capturedLine: 'line 150' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.sourceFile).toBeNull()
        expect(logic.values.fileWindow).toBeNull()
    })
})
