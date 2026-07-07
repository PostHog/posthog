import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DashboardType, QueryBasedInsightModel } from '~/types'

import { textCardModalLogic } from './textCardModalLogic'

const makeDashboard = (body: string = 'existing text'): DashboardType<QueryBasedInsightModel> =>
    ({
        id: 123,
        name: 'Test dashboard',
        description: '',
        pinned: false,
        created_at: '2024-01-01T00:00:00Z',
        created_by: null,
        last_accessed_at: null,
        is_shared: false,
        deleted: false,
        creation_mode: 'default',
        tiles: [
            {
                id: 1,
                color: null,
                layouts: {},
                text: {
                    body,
                    last_modified_at: '2024-01-01T00:00:00Z',
                },
            },
        ],
        filters: {},
        tags: [],
        user_access_level: AccessControlLevel.Editor,
    }) as DashboardType<QueryBasedInsightModel>

describe('textCardModalLogic', () => {
    beforeEach(() => {
        useMocks({
            get: { '/api/environments/:team_id/dashboards/123/': () => [200, makeDashboard()] },
        })
        initKeaTests()
        jest.spyOn(lemonToast, 'error').mockImplementation(jest.fn())
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('creates a new text tile at the pending insertion slot instead of an empty column', async () => {
        const dashboard = makeDashboard('')
        // the inline "+" bar records where the tile should land before opening the modal
        const dashLogic = dashboardLogic({ id: dashboard.id, dashboard })
        dashLogic.mount()
        dashLogic.actions.setPendingInsertion({ x: 6, y: 4, w: null })

        const updateSpy = jest.spyOn(api, 'update').mockResolvedValue(dashboard as any)

        const logic = textCardModalLogic({ dashboard, textTileId: 'new', onClose: jest.fn() })
        logic.mount()
        logic.actions.setTextTileValue('body', 'hello')
        logic.actions.submitTextTile()
        await expectLogic(logic).toFinishAllListeners()

        const patchBody = updateSpy.mock.calls[0][1] as { tiles: { layouts?: unknown }[] }
        expect(patchBody.tiles[0].layouts).toEqual({ sm: { x: 6, y: 4, w: 2, h: 2 } })
    })

    it('omits layouts when there is no pending insertion (header add appends normally)', async () => {
        const dashboard = makeDashboard('')
        dashboardLogic({ id: dashboard.id, dashboard }).mount()

        const updateSpy = jest.spyOn(api, 'update').mockResolvedValue(dashboard as any)

        const logic = textCardModalLogic({ dashboard, textTileId: 'new', onClose: jest.fn() })
        logic.mount()
        logic.actions.setTextTileValue('body', 'hello')
        logic.actions.submitTextTile()
        await expectLogic(logic).toFinishAllListeners()

        const patchBody = updateSpy.mock.calls[0][1] as { tiles: { layouts?: unknown }[] }
        expect(patchBody.tiles[0].layouts).toBeUndefined()
    })

    it('does not show toast for expected form validation errors', async () => {
        const logic = textCardModalLogic({
            dashboard: makeDashboard('x'.repeat(4001)),
            textTileId: 1,
            onClose: jest.fn(),
        })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            textTileValidationErrors: { body: 'Text is too long (4000 characters max)' },
        })

        logic.actions.submitTextTileFailure({ error: 'Validation failed', errors: {} } as any, {})

        expect(lemonToast.error).not.toHaveBeenCalled()
    })

    it('rejects empty text card body in form validation', async () => {
        const logic = textCardModalLogic({
            dashboard: makeDashboard(''),
            textTileId: 'new',
            onClose: jest.fn(),
        })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            textTileValidationErrors: { body: 'This card would be empty! Type something first' },
        })

        logic.actions.submitTextTileFailure({ error: 'Validation failed', errors: {} } as any, {})

        expect(lemonToast.error).not.toHaveBeenCalled()
    })

    it('does not show toast for expected api body validation errors', () => {
        const logic = textCardModalLogic({
            dashboard: makeDashboard('valid'),
            textTileId: 1,
            onClose: jest.fn(),
        })
        logic.mount()

        logic.actions.submitTextTileFailure(
            {
                error: 'Validation failed',
                errors: {},
            } as any,
            { body: ['Text is too long (4000 characters max)'] }
        )

        expect(lemonToast.error).not.toHaveBeenCalled()
    })

    it('shows toast for unexpected submit failures', () => {
        const logic = textCardModalLogic({
            dashboard: makeDashboard('valid'),
            textTileId: 1,
            onClose: jest.fn(),
        })
        logic.mount()

        logic.actions.submitTextTileFailure(
            {
                error: 'Network error',
                errors: {},
            } as any,
            {}
        )

        expect(lemonToast.error).toHaveBeenCalledWith('Could not save text: Network error')
    })
})
