import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import type { PendingInsertion } from 'scenes/dashboard/dashboardLogic'

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
        initKeaTests()
        jest.spyOn(lemonToast, 'error').mockImplementation(jest.fn())
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each([
        {
            scenario: 'with a pending insertion slot',
            pendingInsertion: { x: 6, y: 4, w: null } as PendingInsertion,
            expectedLayouts: { sm: { x: 6, y: 4, w: 2, h: 2 } },
        },
        {
            scenario: 'without a pending insertion slot',
            pendingInsertion: null,
            expectedLayouts: undefined,
        },
    ])('creates a new text tile $scenario', async ({ pendingInsertion, expectedLayouts }) => {
        const dashboard = makeDashboard('')
        const updateSpy = jest.spyOn(api, 'update').mockResolvedValue(dashboard as any)

        const logic = textCardModalLogic({ dashboard, textTileId: 'new', onClose: jest.fn(), pendingInsertion })
        logic.mount()
        logic.actions.setTextTileValue('body', 'hello')
        logic.actions.submitTextTile()
        await expectLogic(logic).toFinishAllListeners()

        const patchBody = updateSpy.mock.calls[0][1] as { tiles: { layouts?: unknown }[] }
        expect(patchBody.tiles[0].layouts).toEqual(expectedLayouts)
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
