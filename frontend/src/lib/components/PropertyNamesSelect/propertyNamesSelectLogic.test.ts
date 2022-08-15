import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { propertySelectLogic } from './propertyNamesSelectLogic'

describe('propertyNamesSelectLogic', () => {
    let logic: ReturnType<typeof propertySelectLogic.build>
    const allProperties: string[] = ['property 1', 'property 2']

    beforeEach(() => {
        initKeaTests()
        logic = propertySelectLogic({
            initialProperties: new Set() as Set<string>,
            onChange: jest.fn(),
            propertySelectLogicKey: '123',
            properties: allProperties,
        })
        logic.mount()
    })

    describe('popover', () => {
        it('should be hidden initially', () => {
            expect(logic.values.isPopoverOpen).toBe(false)
        })

        it('should be open when we trigger togglePopover, then hidden if we do so again', () => {
            expectLogic(logic, () => logic.actions.togglePopover()).toMatchValues({
                isPopoverOpen: true,
            })

            expectLogic(logic, () => logic.actions.togglePopover()).toMatchValues({
                isPopoverOpen: false,
            })
        })

        it('should hide on clicking outside popover element', () => {
            const popoverElement = document.createElement('div')

            logic.actions.setPopoverTriggerElement(popoverElement)

            expectLogic(logic, () => logic.actions.togglePopover()).toMatchValues({
                isPopoverOpen: true,
            })

            document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))

            expect(logic.values.isPopoverOpen).toBe(false)
        })
    })

    describe('property search', () => {
        it('should have not filtered anything on initial load', () => {
            expect(logic.values.filteredProperties).toEqual(
                allProperties.map((property) => ({ name: property, highlightedNameParts: [property] }))
            )
        })

        it('should substring filter based on query', () => {
            expectLogic(logic, () => logic.actions.setQuery('erty 1')).toMatchValues({
                filteredProperties: [
                    {
                        name: logic.values.properties[0],
                        highlightedNameParts: ['prop', 'erty 1', ''],
                    },
                ],
            })
        })
    })

    // TODO: add tests for property selection
})
