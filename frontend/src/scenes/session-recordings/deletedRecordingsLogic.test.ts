import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { deletedRecordingsLogic } from './deletedRecordingsLogic'

describe('deletedRecordingsLogic', () => {
    let logic: ReturnType<typeof deletedRecordingsLogic.build>

    beforeEach(() => {
        localStorage.clear()
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

    it('deduplicates IDs', () => {
        logic.actions.addDeletedRecordings(['abc', 'def'])
        logic.actions.addDeletedRecordings(['abc'])
        expectLogic(logic).toMatchValues({
            deletedRecordingIds: new Set(['abc', 'def']),
        })
    })

    it('keeps deleted IDs after the logic is remounted, e.g. on reload', () => {
        logic.actions.addDeletedRecordings(['abc', 'def'])
        logic.unmount()

        const remounted = deletedRecordingsLogic()
        remounted.mount()
        expectLogic(remounted).toMatchValues({
            deletedRecordingIds: new Set(['abc', 'def']),
        })
    })
})
