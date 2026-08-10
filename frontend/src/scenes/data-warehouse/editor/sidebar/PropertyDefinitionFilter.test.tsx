import { fireEvent, render, screen } from '@testing-library/react'

import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from 'lib/ui/DropdownMenu/DropdownMenu'

import { PropertyDefinitionFilter } from './PropertyDefinitionFilter'

describe('PropertyDefinitionFilter', () => {
    it('closes the filter menu when Enter is pressed', () => {
        render(
            <DropdownMenu defaultOpen>
                <DropdownMenuTrigger>Filter</DropdownMenuTrigger>
                <DropdownMenuContent>
                    <PropertyDefinitionFilter
                        propertyDefinitionKey="events:properties"
                        propertyDefinitionSearch="browser"
                        propertyDefinitionTarget={{ type: 'event' }}
                        setPropertyDefinitionSearch={jest.fn()}
                    />
                </DropdownMenuContent>
            </DropdownMenu>
        )

        const filterInput = screen.getByPlaceholderText('Filter properties')
        fireEvent.keyDown(filterInput, { key: 'Enter' })

        expect(screen.queryByPlaceholderText('Filter properties')).toBeNull()
    })
})
