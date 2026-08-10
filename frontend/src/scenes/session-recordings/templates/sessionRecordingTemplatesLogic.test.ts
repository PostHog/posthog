import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { ReplayTemplateType, ReplayTemplateVariableType } from '~/types'

import { sessionReplayTemplatesLogic } from './sessionRecordingTemplatesLogic'

const templateWith = (variables: ReplayTemplateVariableType[]): ReplayTemplateType => ({
    key: 'test',
    name: 'Test',
    description: 'Test template',
    variables,
    categories: ['B2B'],
})

describe('sessionReplayTemplatesLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    describe('canApplyFilters', () => {
        const cases: [string, ReplayTemplateVariableType[], boolean][] = [
            ['no variables', [], true],
            [
                'pageview with a default value',
                [{ type: 'pageview', name: 'URL', key: 'url', value: '/purchase' }],
                true,
            ],
            ['pageview without a value', [{ type: 'pageview', name: 'URL', key: 'url' }], false],
            ['flag without a value', [{ type: 'flag', name: 'Flag', key: 'flag' }], false],
            ['event without a filter group', [{ type: 'event', name: 'Event', key: 'event' }], false],
            [
                'preset noTouch variable',
                [
                    {
                        type: 'event',
                        name: 'Rageclick',
                        key: 'rageclick',
                        noTouch: true,
                        filterGroup: { id: '$rageclick', name: '$rageclick', type: 'events' },
                    },
                ],
                true,
            ],
        ]

        it.each(cases)('%s', async (_name, variables, expected) => {
            const logic = sessionReplayTemplatesLogic({ template: templateWith(variables), category: 'B2B' })
            logic.mount()
            await expectLogic(logic).toMatchValues({ canApplyFilters: expected })
        })

        it('turns true once an editable variable gets a value, and false again when it is cleared', async () => {
            const variable: ReplayTemplateVariableType = { type: 'pageview', name: 'URL', key: 'url' }
            const logic = sessionReplayTemplatesLogic({ template: templateWith([variable]), category: 'B2B' })
            logic.mount()
            await expectLogic(logic).toMatchValues({ canApplyFilters: false })

            logic.actions.setVariable({ ...variable, value: '/checkout' })
            await expectLogic(logic).toMatchValues({ canApplyFilters: true })

            logic.actions.resetVariable({ ...variable, value: undefined })
            await expectLogic(logic).toMatchValues({ canApplyFilters: false })
        })
    })
})
