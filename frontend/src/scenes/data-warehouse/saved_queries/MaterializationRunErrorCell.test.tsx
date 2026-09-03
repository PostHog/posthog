import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { MaterializationRunErrorCell } from './MaterializationRunErrorCell'

describe('MaterializationRunErrorCell', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(cleanup)

    it('shows the first line in the cell and the full error in a dialog', async () => {
        const error = 'ClickHouse error: Code 62\nDB::Exception: Syntax error\n  at line 3'
        render(<MaterializationRunErrorCell error={error} status="Failed" />)

        expect(screen.getByText('ClickHouse error: Code 62')).toBeInTheDocument()
        expect(screen.queryByText(/DB::Exception/)).not.toBeInTheDocument()

        fireEvent.click(screen.getByText('View'))

        expect(await screen.findByText('Run error')).toBeInTheDocument()
        expect(screen.getByText(/DB::Exception: Syntax error/)).toBeInTheDocument()
        expect(screen.getByText('Copy')).toBeInTheDocument()

        fireEvent.click(screen.getByText('Close'))
    })
})
