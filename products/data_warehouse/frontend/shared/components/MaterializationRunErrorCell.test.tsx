import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { initKeaTests } from '~/test/init'
import { DataModelingJobStatus } from '~/types'

import { MaterializationRunErrorCell } from './MaterializationRunErrorCell'

describe('MaterializationRunErrorCell', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(cleanup)

    it.each<[DataModelingJobStatus, string]>([
        ['Failed', 'Run error'],
        ['Skipped', 'Skip reason'],
    ])('shows the first line in the cell and the full %s text in a dialog titled %s', async (status, title) => {
        const error = 'ClickHouse error: Code 62\nDB::Exception: Syntax error\n  at line 3'
        render(<MaterializationRunErrorCell error={error} status={status} />)

        expect(screen.getByText('ClickHouse error: Code 62')).toBeInTheDocument()
        expect(screen.queryByText(/DB::Exception/)).not.toBeInTheDocument()

        fireEvent.click(screen.getByText('View'))

        expect(await screen.findByText(title)).toBeInTheDocument()
        expect(screen.getByText(/DB::Exception: Syntax error/)).toBeInTheDocument()
        expect(screen.getByText('Copy')).toBeInTheDocument()

        fireEvent.click(screen.getByText('Close'))
        await waitFor(() => expect(screen.queryByText(title)).not.toBeInTheDocument())
    })
})
