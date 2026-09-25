import { waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { experimentPickerLogic } from './experimentPickerLogic'

const creator = { id: 1, uuid: 'u-1', email: 'alex@example.test', first_name: 'Alex', last_name: 'Chen' }
const experiment = (id: number, name: string): Record<string, unknown> => ({ id, name, created_by: creator })

describe('experimentPickerLogic', () => {
    let logic: ReturnType<typeof experimentPickerLogic.build>
    let listMock: jest.Mock
    let retrieveMock: jest.Mock
    let lastSearch: string | null = null

    beforeEach(() => {
        lastSearch = null
        listMock = jest.fn(({ request }) => {
            lastSearch = new URL(request.url).searchParams.get('search')
            return [200, { results: [experiment(101, 'New signup CTA'), experiment(102, 'Pricing page')], count: 2 }]
        })
        retrieveMock = jest.fn(({ params }) => [200, experiment(Number(params.id), `Experiment ${params.id}`)])
        useMocks({
            get: {
                '/api/projects/:team_id/experiments/': listMock,
                '/api/projects/:team_id/experiments/:id/': retrieveMock,
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('does not load experiments until the dropdown is opened', async () => {
        logic = experimentPickerLogic({ pickerKey: 'tile-1' })
        logic.mount()
        expect(logic.values.experimentOptions).toEqual([])
        expect(listMock).not.toHaveBeenCalled()

        logic.actions.ensureOptionsLoaded()
        await waitFor(() => expect(logic.values.experimentOptions).toHaveLength(2))
        expect(logic.values.hasLoadedOptions).toBe(true)
    })

    it('only loads the option list once across repeated focus', async () => {
        logic = experimentPickerLogic({ pickerKey: 'tile-1' })
        logic.mount()
        logic.actions.ensureOptionsLoaded()
        await waitFor(() => expect(logic.values.hasLoadedOptions).toBe(true))
        logic.actions.ensureOptionsLoaded()
        await new Promise((resolve) => setTimeout(resolve, 50))
        expect(listMock).toHaveBeenCalledTimes(1)
    })

    it('runs a server-side search and passes the term', async () => {
        logic = experimentPickerLogic({ pickerKey: 'tile-1' })
        logic.mount()
        logic.actions.setSearch('signup')
        await waitFor(() => expect(lastSearch).toBe('signup'))
    })

    it('resolves the selected experiment by id and skips reloading the same id', async () => {
        logic = experimentPickerLogic({ pickerKey: 'tile-1' })
        logic.mount()
        logic.actions.ensureSelectedLoaded(555)
        await waitFor(() => expect(logic.values.selectedExperiment?.id).toBe(555))
        expect(retrieveMock).toHaveBeenCalledTimes(1)

        logic.actions.ensureSelectedLoaded(555)
        await new Promise((resolve) => setTimeout(resolve, 50))
        expect(retrieveMock).toHaveBeenCalledTimes(1)
    })

    it('isolates state across distinct picker keys', () => {
        const tileLogic = experimentPickerLogic({ pickerKey: 'tile-1' })
        const modalLogic = experimentPickerLogic({ pickerKey: 'results-modal' })
        expect(tileLogic.pathString).not.toEqual(modalLogic.pathString)
    })
})
