import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { deletedRecordingsLogic } from './deletedRecordingsLogic'

describe('deletedRecordingsLogic', () => {
    let logic: ReturnType<typeof deletedRecordingsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = deletedRecordingsLogic()
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
