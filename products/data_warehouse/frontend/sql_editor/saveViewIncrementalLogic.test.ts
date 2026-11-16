import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonDialogLogic } from 'lib/lemon-ui/LemonDialog/lemonDialogLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import type { IncrementalEligibilityApi } from '../generated/api.schemas'
import { saveViewIncrementalLogic } from './saveViewIncrementalLogic'

const ELIGIBLE_CHECK: IncrementalEligibilityApi = {
    eligible: true,
    key_candidates: ['timestamp'],
    unique_key_candidates: ['id', 'timestamp'],
    key_candidate_types: { timestamp: 'datetime', id: 'integer' },
    blockers: [],
    warnings: [],
}

describe('saveViewIncrementalLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('keeps the name editable during the check and sets the first incremental column after it completes', async () => {
        let finishCheck!: (check: IncrementalEligibilityApi) => void
        const checkRequest = jest
            .spyOn(api, 'warehouseSavedQueriesCheckIncrementalCreate')
            .mockImplementation(() => new Promise((resolve) => (finishCheck = resolve)))
        const form = lemonDialogLogic({ dialogKey: 'save-view' })
        form.mount()
        form.actions.setFormValue('viewName', 'daily_events')
        const logic = saveViewIncrementalLogic({
            dialogKey: 'save-view',
            query: 'SELECT timestamp, id FROM events',
            enabled: true,
        })
        logic.mount()

        expect(logic.values.checkLoading).toBe(true)
        expect(form.values.form).not.toHaveProperty('incrementalEnabled')
        await waitFor(() => expect(checkRequest).toHaveBeenCalledTimes(1))
        expect(form.values.isFormValid).toBe(true)
        form.actions.setFormValue('viewName', 'edited_name')
        finishCheck(ELIGIBLE_CHECK)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.check).toEqual(ELIGIBLE_CHECK)
        expect(form.values.form).toMatchObject({ viewName: 'edited_name', incrementalKey: 'timestamp' })
        logic.unmount()
        form.unmount()
    })

    it('discards an old response when the selected SQL changes', async () => {
        let finishOldCheck!: (check: IncrementalEligibilityApi) => void
        const checkRequest = jest
            .spyOn(api, 'warehouseSavedQueriesCheckIncrementalCreate')
            .mockImplementationOnce(() => new Promise((resolve) => (finishOldCheck = resolve)))
            .mockResolvedValueOnce({ ...ELIGIBLE_CHECK, key_candidates: ['created_at'] })
        const form = lemonDialogLogic({ dialogKey: 'save-view' })
        form.mount()
        const oldLogic = saveViewIncrementalLogic({
            dialogKey: 'save-view',
            query: 'SELECT timestamp FROM events',
            enabled: true,
        })
        oldLogic.mount()
        await waitFor(() => expect(checkRequest).toHaveBeenCalledTimes(1))
        form.actions.setFormValue('incrementalEnabled', true)
        form.actions.setFormValue('incrementalUniqueKey', ['id'])
        oldLogic.unmount()

        const newLogic = saveViewIncrementalLogic({
            dialogKey: 'save-view',
            query: 'SELECT created_at FROM persons',
            enabled: true,
        })
        newLogic.mount()
        await expectLogic(newLogic).toDispatchActions(['loadCheckSuccess'])
        finishOldCheck(ELIGIBLE_CHECK)
        await expectLogic(oldLogic).toFinishAllListeners()

        expect(form.values.form).toMatchObject({
            incrementalEnabled: false,
            incrementalKey: 'created_at',
            incrementalUniqueKey: [],
        })
        newLogic.unmount()
        form.unmount()
    })

    it('keeps the form usable with a full refresh when the check fails', async () => {
        const error = new Error('Check unavailable')
        jest.spyOn(api, 'warehouseSavedQueriesCheckIncrementalCreate').mockRejectedValue(error)
        const captureException = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
        const form = lemonDialogLogic({ dialogKey: 'save-view' })
        form.mount()
        form.actions.setFormValue('viewName', 'daily_events')
        const logic = saveViewIncrementalLogic({
            dialogKey: 'save-view',
            query: 'SELECT timestamp FROM events',
            enabled: true,
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.checkLoading).toBe(false)
        expect(logic.values.check).toBeNull()
        expect(form.values.isFormValid).toBe(true)
        expect(form.values.form).toMatchObject({ viewName: 'daily_events', incrementalEnabled: false })
        expect(captureException).toHaveBeenCalledWith(error)
        logic.unmount()
        form.unmount()
    })

    it('loads only after materialization is selected and preserves settings when it is toggled', async () => {
        const checkRequest = jest
            .spyOn(api, 'warehouseSavedQueriesCheckIncrementalCreate')
            .mockResolvedValue(ELIGIBLE_CHECK)
        const form = lemonDialogLogic({ dialogKey: 'save-view' })
        form.mount()
        const props = { dialogKey: 'save-view', query: 'SELECT timestamp, id FROM events', enabled: false }
        const logic = saveViewIncrementalLogic(props)
        logic.mount()
        expect(checkRequest).not.toHaveBeenCalled()

        saveViewIncrementalLogic({ ...props, enabled: true })
        await expectLogic(logic).toFinishAllListeners()
        form.actions.setFormValue('incrementalEnabled', true)
        form.actions.setFormValue('incrementalUniqueKey', ['id'])
        form.actions.setFormValue('incrementalLookbackSeconds', 3600)
        saveViewIncrementalLogic({ ...props, enabled: false })
        saveViewIncrementalLogic({ ...props, enabled: true })
        await expectLogic(logic).toFinishAllListeners()

        expect(checkRequest).toHaveBeenCalledTimes(1)
        expect(form.values.form).toMatchObject({
            incrementalEnabled: true,
            incrementalKey: 'timestamp',
            incrementalUniqueKey: ['id'],
            incrementalLookbackSeconds: 3600,
        })
        logic.unmount()
        form.unmount()
    })

    it('does not request an incremental check without a project', async () => {
        const checkRequest = jest.spyOn(api, 'warehouseSavedQueriesCheckIncrementalCreate')
        teamLogic.actions.loadCurrentTeamSuccess(null)
        const logic = saveViewIncrementalLogic({ dialogKey: 'save-view', query: 'SELECT 1', enabled: true })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(checkRequest).not.toHaveBeenCalled()
        expect(logic.values.checkLoading).toBe(false)
        expect(logic.values.check).toBeNull()
        logic.unmount()
    })
})
