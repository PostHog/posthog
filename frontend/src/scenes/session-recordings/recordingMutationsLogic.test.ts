import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { recordingMutationsLogic } from './recordingMutationsLogic'

describe('recordingMutationsLogic', () => {
    let logic: ReturnType<typeof recordingMutationsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = recordingMutationsLogic()
        logic.mount()
    })

    it('starts with empty set', () => {
        expectLogic(logic).toMatchValues({
            deletedRecordingIds: new Set(),
        })
    })

    it('adds deleted recording IDs', () => {
        logic.actions.addDeletedRecordings(['abc', 'def'])
        expectLogic(logic).toMatchValues({
            deletedRecordingIds: new Set(['abc', 'def']),
        })
    })

    it('accumulates across multiple calls', () => {
        logic.actions.addDeletedRecordings(['abc'])
        logic.actions.addDeletedRecordings(['def', 'ghi'])
        expectLogic(logic).toMatchValues({
            deletedRecordingIds: new Set(['abc', 'def', 'ghi']),
        })
    })

    it('deduplicates IDs', () => {
        logic.actions.addDeletedRecordings(['abc', 'def'])
        logic.actions.addDeletedRecordings(['abc'])
        expectLogic(logic).toMatchValues({
            deletedRecordingIds: new Set(['abc', 'def']),
        })
    })
})
