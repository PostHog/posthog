import { initKeaTests } from '~/test/init'
import { definitionPanelLogic } from 'lib/components/DefinitionPanel/definitionPanelLogic'
import { expectLogic } from 'kea-test-utils'
import { mockAPI } from 'lib/api.mock'
import { mockEventDefinitions } from '~/test/mocks'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
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
                logic.actions.openDrawer('id', TaxonomicFilterGroupType.Events)
            })
                .toDispatchActions(['openDrawer', 'loadDefinition', 'loadDefinitionSuccess'])
                .toMatchValues({
                    type: TaxonomicFilterGroupType.Events,
                    visible: true,
                    definition: {
                        results: mockEventDefinitions,
                        count: mockEventDefinitions.length,
                    },
                })
        })
        it('closes modal', async () => {
            await expectLogic(logic, () => {
                logic.actions.openDrawer('id', TaxonomicFilterGroupType.Events)
            })
                .toDispatchActions(['openDrawer', 'loadDefinition', 'loadDefinitionSuccess'])
                .toMatchValues({
                    visible: true,
                    type: TaxonomicFilterGroupType.Events,
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
