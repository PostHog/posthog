import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { experimentPickerLogic } from './experimentPickerLogic'

const creator = { id: 1, uuid: 'u-1', email: 'alex@example.test', first_name: 'Alex', last_name: 'Chen' }
const experiment = (id: number, name: string): Record<string, unknown> => ({ id, name, created_by: creator })

describe('experimentPickerLogic', () => {
    let logic: ReturnType<typeof experimentPickerLogic.build>
    let listMock: jest.Mock

    beforeEach(() => {
        listMock = jest.fn(() => [
            200,
            { results: [experiment(101, 'New signup CTA'), experiment(102, 'Pricing page')], count: 2 },
        ])
        useMocks({
            get: {
                '/api/projects/:team_id/experiments/': listMock,
                '/api/projects/:team_id/experiments/:id/': (req) => [
                    200,
                    experiment(Number(req.params.id), `Experiment ${req.params.id}`),
                ],
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

        await expectLogic(logic, () => logic.actions.ensureOptionsLoaded()).toDispatchActions([
            'loadOptions',
            'loadOptionsSuccess',
        ])
        expect(logic.values.experimentOptions).toHaveLength(2)
        expect(logic.values.hasLoadedOptions).toBe(true)
    })

    it('only loads the option list once across repeated focus', async () => {
        logic = experimentPickerLogic({ pickerKey: 'tile-1' })
        logic.mount()
        await expectLogic(logic, () => logic.actions.ensureOptionsLoaded()).toDispatchActions(['loadOptionsSuccess'])
        await expectLogic(logic, () => logic.actions.ensureOptionsLoaded()).toFinishAllListeners()
        expect(listMock).toHaveBeenCalledTimes(1)
    })

    it('runs a server-side search and passes the term', async () => {
        logic = experimentPickerLogic({ pickerKey: 'tile-1' })
        logic.mount()
        await expectLogic(logic, () => logic.actions.setSearch('signup')).toDispatchActions(['loadOptionsSuccess'])
        expect(listMock).toHaveBeenCalled()
        const lastUrl = String(listMock.mock.calls.at(-1)?.[0]?.url ?? '')
        expect(lastUrl).toContain('search=signup')
    })

    it('resolves the selected experiment by id and skips reloading the same id', async () => {
        logic = experimentPickerLogic({ pickerKey: 'tile-1' })
        logic.mount()
        await expectLogic(logic, () => logic.actions.ensureSelectedLoaded(555)).toDispatchActions([
            'loadSelectedExperimentSuccess',
        ])
        expect(logic.values.selectedExperiment?.id).toBe(555)

        await expectLogic(logic, () => logic.actions.ensureSelectedLoaded(555)).toNotHaveDispatchedActions([
            'loadSelectedExperiment',
        ])
    })

    it('isolates state across distinct picker keys', () => {
        const tileLogic = experimentPickerLogic({ pickerKey: 'tile-1' })
        const modalLogic = experimentPickerLogic({ pickerKey: 'results-modal' })
        expect(tileLogic.pathString).not.toEqual(modalLogic.pathString)
    })
})
