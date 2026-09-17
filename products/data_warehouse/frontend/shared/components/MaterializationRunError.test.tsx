import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'
import { DataModelingJobStatus } from '~/types'

import { MaterializationRunError } from './MaterializationRunError'

describe('MaterializationRunError', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(cleanup)

    it.each<[DataModelingJobStatus, string]>([
        ['Failed', 'Run error'],
        ['Skipped', 'Skip reason'],
    ])('keeps the full %s message available to copy under %s', (status, title) => {
        const error = 'ClickHouse error: Code 62\nDB::Exception: Syntax error\n  at line 3'
        render(<MaterializationRunError error={error} status={status} />)

        expect(screen.getByText(title)).toBeInTheDocument()
        expect(screen.getByText(/DB::Exception: Syntax error/)).toBeInTheDocument()
        expect(document.querySelector('[data-attr="copy-code-button"]')).toBeInTheDocument()
    })
})
