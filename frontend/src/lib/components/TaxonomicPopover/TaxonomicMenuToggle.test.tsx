import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { SuppressTaxonomicMenuToggle, TaxonomicMenuToggle } from './TaxonomicMenuToggle'

describe('TaxonomicMenuToggle', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders the menu-switch badge by default', () => {
        render(
            <Provider>
                <TaxonomicMenuToggle />
            </Provider>
        )
        expect(screen.getByTestId('taxonomic-menu-toggle')).toBeInTheDocument()
    })

    it('renders nothing inside SuppressTaxonomicMenuToggle', () => {
        render(
            <Provider>
                <SuppressTaxonomicMenuToggle>
                    <TaxonomicMenuToggle />
                </SuppressTaxonomicMenuToggle>
            </Provider>
        )
        expect(screen.queryByTestId('taxonomic-menu-toggle')).not.toBeInTheDocument()
    })
})
