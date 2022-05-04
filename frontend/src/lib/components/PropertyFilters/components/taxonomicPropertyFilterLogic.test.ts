import { initKeaTests } from '~/test/init'
import { taxonomicPropertyFilterLogic } from 'lib/components/PropertyFilters/components/taxonomicPropertyFilterLogic'
import { expectLogic } from 'kea-test-utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'

describe('the taxonomic property filter', () => {
    let logic: ReturnType<typeof taxonomicPropertyFilterLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = taxonomicPropertyFilterLogic({
            propertyFilterLogic: propertyFilterLogic({
                pageKey: 'tests',
                propertyFilters: [],
                onChange: () => {},
            }),
            taxonomicGroupTypes: [
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.Cohorts,
                TaxonomicFilterGroupType.Elements,
            ],
            filterIndex: 1,
            pageKey: 'test',
        })
        logic.mount()
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
            dropdownOpen: true,
        })
    })
})
