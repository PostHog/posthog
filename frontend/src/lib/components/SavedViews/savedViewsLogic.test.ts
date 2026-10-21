import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { SavedView, savedViewsLogic } from './savedViewsLogic'

const LOGIC_PROPS = { key: 'test', endpoint: 'test-product/views' }

const mockView = (overrides: Partial<SavedView> = {}): SavedView => ({
    id: 'view-1',
    short_id: 'abc123',
    name: 'My view',
    filters: {},
    created_at: '2026-06-01T00:00:00Z',
    created_by: null,
    ...overrides,
})

describe('savedViewsLogic', () => {
    let logic: ReturnType<typeof savedViewsLogic.build>

    beforeEach(() => {
        initKeaTests()
        // openModal triggers loadViews → api.get; keep it from hitting the network.
        jest.spyOn(api, 'get').mockResolvedValue({ results: [] })
        logic = savedViewsLogic(LOGIC_PROPS)
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it.each([
        [
            'saves the trimmed name with the product payload',
            '  Slow spans  ',
            [
                [
                    expect.stringMatching(/\/test-product\/views\/$/),
                    { name: 'Slow spans', filters: { serviceNames: ['api'] } },
                ],
            ],
        ],
        ['does nothing when the name is blank', '   ', []],
    ])('saveView %s', async (_, viewName, expectedCalls) => {
        const createSpy = jest.spyOn(api, 'create').mockResolvedValue(mockView())

        logic.actions.setViewName(viewName)
        await expectLogic(logic, () => {
            logic.actions.saveView({ filters: { serviceNames: ['api'] } })
        }).toFinishAllListeners()

        expect(createSpy.mock.calls).toEqual(expectedCalls)
    })

    it('closes the list modal when a view is loaded', async () => {
        logic.actions.openModal()
        expect(logic.values.isModalOpen).toBe(true)

        logic.actions.loadView(mockView())
        expect(logic.values.isModalOpen).toBe(false)
    })

    it('optimistically removes a deleted view from the list', async () => {
        jest.spyOn(api, 'delete').mockResolvedValue(undefined)
        // Seed the loader state with two views.
        jest.spyOn(api, 'get').mockResolvedValue({
            results: [mockView({ short_id: 'keep' }), mockView({ short_id: 'drop' })],
        })
        await expectLogic(logic, () => {
            logic.actions.loadViews()
        }).toFinishAllListeners()
        expect(logic.values.views).toHaveLength(2)

        logic.actions.deleteView('drop')
        expect(logic.values.views.map((v) => v.short_id)).toEqual(['keep'])
    })
})
