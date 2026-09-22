import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { PropertyDefinitionFilter } from './PropertyDefinitionFilter'

describe('PropertyDefinitionFilter', () => {
    it('closes the filter menu when Enter is pressed', async () => {
        render(
            <PropertyDefinitionFilter
                propertyDefinitionKey="events:properties"
                propertyDefinitionSearch="browser"
                propertyDefinitionTarget={{ type: 'event' }}
                setPropertyDefinitionSearch={jest.fn()}
            />
        )

        fireEvent.click(screen.getByLabelText('Filter properties'))
        const filterInput = screen.getByPlaceholderText('Filter properties')
        fireEvent.keyDown(filterInput, { key: 'Enter' })

        await waitFor(() => expect(screen.queryByPlaceholderText('Filter properties')).toBeNull())
    })
})
