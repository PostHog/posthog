import { createAccountReplayQuery } from './accountSessionReplaysQuery'

const dateRange = { date_from: '-7d', date_to: null }

describe('createAccountReplayQuery', () => {
    it.each([
        { externalId: '', groupTypeIndex: 0 },
        { externalId: '   ', groupTypeIndex: 0 },
        { externalId: 'account-key', groupTypeIndex: undefined },
        { externalId: 'account-key', groupTypeIndex: null },
        { externalId: 'account-key', groupTypeIndex: -1 },
        { externalId: 'account-key', groupTypeIndex: 5 },
        { externalId: 'account-key', groupTypeIndex: 0.5 },
    ])('rejects invalid account identity or group mapping: %p', ({ externalId, groupTypeIndex }) => {
        expect(createAccountReplayQuery(externalId, groupTypeIndex, dateRange, null)).toBeNull()
    })
})
