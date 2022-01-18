import { initKeaTests } from '~/test/init'
import { definitionPanelLogic } from 'lib/components/DefinitionPanel/definitionPanelLogic'
import { expectLogic } from 'kea-test-utils'
import { DefinitionType } from 'lib/components/DefinitionPanel/types'
import { mockAPI } from 'lib/api.mock'
import { mockEventDefinitions } from '~/test/mocks'
jest.mock('lib/api')

describe('definitionPanelLogic', () => {
    let logic: ReturnType<typeof definitionPanelLogic.build>

    mockAPI(async ({ pathname }) => {
        if (pathname.startsWith(`api/projects/@current/event_definitions`)) {
            const results = mockEventDefinitions
            return {
                results,
                count: results.length,
            }
        }
    })

    beforeEach(() => {
        initKeaTests()
        logic = definitionPanelLogic()
        logic.mount()
    })

    describe('open and close modal', () => {
        it('opens modal and loads definitions', async () => {
            await expectLogic(logic, () => {
                logic.actions.openDrawer('id', DefinitionType.Events)
            })
                .toDispatchActions(['openDrawer', 'loadDefinition', 'loadDefinitionSuccess'])
                .toMatchValues({
                    type: DefinitionType.Events,
                    visible: true,
                    definition: {
                        results6: mockEventDefinitions,
                        count: mockEventDefinitions.length,
                    },
                })
        })
        it('closes modal', async () => {
            await expectLogic(logic, () => {
                logic.actions.openDrawer('id', DefinitionType.Events)
            })
                .toDispatchActions(['openDrawer', 'loadDefinition', 'loadDefinitionSuccess'])
                .toMatchValues({
                    visible: true,
                    type: DefinitionType.Events,
                })

            await expectLogic(logic, () => {
                logic.actions.closeDrawer()
            })
                .toDispatchActions(['closeDrawer'])
                .toMatchValues({
                    visible: false,
                    type: null,
                })
        })
    })
})
