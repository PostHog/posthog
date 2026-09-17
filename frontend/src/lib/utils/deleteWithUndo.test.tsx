import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'

import { recentItemsModel } from '~/models/recentItemsModel'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { QueryBasedInsightModel } from '~/types'

import { deleteInsightWithUndo } from './deleteWithUndo'

const insight = { id: 1, short_id: 'abc123', name: 'Weekly signups' } as unknown as QueryBasedInsightModel
const recentInsight = { id: 'entry', path: 'Weekly signups', type: 'insight', ref: 'abc123' } as FileSystemEntry

describe('deleteInsightWithUndo', () => {
    beforeEach(() => {
        initKeaTests(false)
        recentItemsModel.mount()
        recentItemsModel.actions.loadRecentsSuccess([recentInsight])
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('treats a 404 as already deleted and drops the insight from recents', async () => {
        jest.spyOn(api, 'update').mockRejectedValue(
            new ApiError('Not found.', 404, undefined, { detail: 'Not found.' })
        )
        const errorToast = jest.spyOn(lemonToast, 'error')

        // The insight is gone, so the delete counts as done — the user must not read the raw
        // "Not found." as a destructive action that failed.
        await expect(deleteInsightWithUndo({ endpoint: 'projects/1/insights', object: insight })).resolves.toBe(true)
        expect(errorToast).not.toHaveBeenCalled()
        expect(recentItemsModel.values.recents).toEqual([])
    })

    it('reports a failed delete and keeps the insight in recents', async () => {
        jest.spyOn(api, 'update').mockRejectedValue(new ApiError('Server error', 500))
        const errorToast = jest.spyOn(lemonToast, 'error')

        await expect(deleteInsightWithUndo({ endpoint: 'projects/1/insights', object: insight })).resolves.toBe(false)
        expect(errorToast).toHaveBeenCalled()
        expect(recentItemsModel.values.recents).toEqual([recentInsight])
    })
})
