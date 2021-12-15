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

    mockAPI(defaultAPIMocks)

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

    it('starts with dropdown closed', async () => {
        await expectLogic(logic).toMatchValues({
            dropdownOpen: false,
        })
    })

    it('closes the dropdown onCloseDropdown', async () => {
        await expectLogic(logic, () => {
            logic.actions.openDropdown()
            logic.actions.closeDropdown()
        }).toMatchValues({
            dropdownOpen: false,
        })
    })

    it('opens the dropdown onOpenDropdown', async () => {
        await expectLogic(logic, () => {
            logic.actions.openDropdown()
        }).toMatchValues({
            dropdownHeldOpen: false,
            dropdownMightOpen: true,
            dropdownOpen: true,
        })
    })
    it('does not close the dropdown onCloseDropdown when locked open', async () => {
        await expectLogic(logic, () => {
            logic.actions.openDropdown()
            logic.actions.holdDropdownOpen(true)
            logic.actions.closeDropdown()
        }).toMatchValues({
            dropdownHeldOpen: true,
            dropdownMightOpen: false,
            dropdownOpen: true,
        })
    })

    it('can release a hold when locked open', async () => {
        await expectLogic(logic, () => {
            logic.actions.openDropdown()
            logic.actions.holdDropdownOpen(true)
            logic.actions.holdDropdownOpen(false)
            logic.actions.closeDropdown()
        }).toMatchValues({
            dropdownHeldOpen: false,
            dropdownMightOpen: false,
            dropdownOpen: false,
        })
    })
})
