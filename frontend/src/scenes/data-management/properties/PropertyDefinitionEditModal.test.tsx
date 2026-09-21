import '@testing-library/jest-dom'

import { cleanup, render, screen, within } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { PropertyDefinitionEditModal } from './PropertyDefinitionEditModal'
import type { PropertyDefinitionEditModalProps } from './propertyDefinitionEditModalLogic'

describe('PropertyDefinitionEditModal', () => {
    afterEach(cleanup)

    it('shows the editable property definition fields', () => {
        useMocks({
            get: {
                '/api/projects/:team/tags/': [],
            },
        })
        initKeaTests()

        const propertyDefinition = {
            id: 'property-id',
            name: 'plan',
            description: 'Billing plan',
            tags: ['billing'],
            property_type: 'String',
            verified: false,
            hidden: false,
        } as PropertyDefinitionEditModalProps['propertyDefinition']

        render(
            <PropertyDefinitionEditModal
                propertyDefinition={propertyDefinition}
                onClose={jest.fn()}
                onSave={jest.fn()}
            />
        )

        const dialog = screen.getByRole('dialog')
        expect(within(dialog).getByText('Edit definition')).toBeInTheDocument()
        expect(within(dialog).getByText('plan')).toBeInTheDocument()
        expect(within(dialog).getByText('Tags')).toBeInTheDocument()
        expect(within(dialog).getByText('Description')).toBeInTheDocument()
        expect(within(dialog).getByText('Status')).toBeInTheDocument()
        expect(within(dialog).getByText('Property type')).toBeInTheDocument()
        expect(dialog.querySelector('[data-attr="save-property-definition"]')).toHaveAttribute('aria-disabled', 'true')
    })
})
