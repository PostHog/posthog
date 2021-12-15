import { initKeaTestLogic } from '~/test/init'
import { taxonomicPropertyFilterLogic } from 'lib/components/PropertyFilters/components/taxonomicPropertyFilterLogic'
import { BuiltLogic } from 'kea'
import { taxonomicPropertyFilterLogicType } from 'lib/components/PropertyFilters/components/taxonomicPropertyFilterLogicType'
import { expectLogic } from 'kea-test-utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { defaultAPIMocks, mockAPI } from 'lib/api.mock'

jest.mock('lib/api')

describe('the taxonomic property filter', () => {
    let logic: BuiltLogic<taxonomicPropertyFilterLogicType>

    mockAPI(async (url) => {
        console.log(url)
        return defaultAPIMocks(url)
    })

    initKeaTestLogic({
        logic: taxonomicPropertyFilterLogic,
        props: {
            taxonomicGroupTypes: [
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.Cohorts,
                TaxonomicFilterGroupType.Elements,
            ],
            filterIndex: 1,
            pageKey: 'test',
        },
        onLogic: (l) => (logic = l),
    })
    it('closes the dropdown onCloseDropdown', () => {
        expectLogic(logic, () => {
            logic.actions.openDropdown
            logic.actions.closeDropdown
        }).toMatchValues({
            dropdownOpen: true,
        })
    })
    it.todo('opens the dropdown onOpenDropdown')
    it.todo('does not close the dropdown onCloseDropdown when locked open')
})
