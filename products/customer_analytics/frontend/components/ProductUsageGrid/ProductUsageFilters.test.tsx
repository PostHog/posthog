import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ProductUsageFilters } from './ProductUsageFilters'
import { productUsageGridLogic } from './productUsageGridLogic'

afterEach(() => cleanup())

describe('ProductUsageFilters', () => {
    it('loads role choices before an activity query and applies the chosen role', async () => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team_id/account_relationship_definitions/': {
                    count: 1,
                    next: null,
                    results: [
                        {
                            id: 'role-1',
                            name: 'Demo account manager',
                            description: null,
                            is_single_holder: true,
                            is_controlled: false,
                        },
                    ],
                },
            },
        })
        render(<ProductUsageFilters />)
        fireEvent.click(screen.getByRole('button', { name: 'All roles' }))
        fireEvent.click(await screen.findByRole('menuitem', { name: 'Demo account manager' }))
        expect(productUsageGridLogic.values.controls.relationshipId).toBe('role-1')
        expect(productUsageGridLogic.values.result).toBeNull()
    })
})
