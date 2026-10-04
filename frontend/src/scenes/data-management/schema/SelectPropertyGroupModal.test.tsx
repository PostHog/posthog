import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { SelectPropertyGroupModal } from 'scenes/data-management/schema/SelectPropertyGroupModal'

import { useMocks } from '~/mocks/jest'
import { getByDataAttr } from '~/test/byDataAttr'
import { initKeaTests } from '~/test/init'

describe('SelectPropertyGroupModal', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/schema_property_groups/': { results: [] },
            },
        })
        initKeaTests()
    })
    afterEach(cleanup)

    it('opens the create form from the empty state', async () => {
        render(<SelectPropertyGroupModal isOpen onClose={jest.fn()} onSelect={jest.fn()} />)
        await waitFor(() => expect(screen.getByText('No property groups yet.')).toBeInTheDocument())
        fireEvent.click(getByDataAttr(document.body, 'select-property-group-empty-create'))
        expect(screen.getByText('New property group', { selector: 'h3' })).toBeInTheDocument()
    })
})
