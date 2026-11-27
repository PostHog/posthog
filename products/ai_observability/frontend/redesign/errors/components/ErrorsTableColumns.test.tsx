import { cleanup, render } from '@testing-library/react'

import { LemonTable } from 'lib/lemon-ui/LemonTable'

import { initKeaTests } from '~/test/init'

import type { ErrorListItemApi } from '../../../generated/api.schemas'
import type { CellLoads } from '../../shared/cellLoads'
import type { ErrorFirstSeen } from '../errorFirstSeenLogic'
import { makeErrorListItem } from '../testFixtures'
import { errorsTableColumns } from './ErrorsTableColumns'

const READ = { firstSeen: '2026-09-02T08:30:00Z', checkedFrom: '2026-08-02' }

function changeCell(firstSeen: CellLoads<ErrorFirstSeen>): string {
    initKeaTests()
    const { container } = render(
        <LemonTable<ErrorListItemApi>
            columns={errorsTableColumns({
                maxOccurrences: 128,
                order: 'occurrences',
                onOrder: () => {},
                firstSeen,
                timezone: 'UTC',
                'data-attr': 'errors-list',
            })}
            dataSource={[makeErrorListItem({ key: 'error-1', changeLabel: 'was 0' })]}
            rowKey={(row) => row.key}
        />
    )
    return container.querySelectorAll('tbody td')[2]?.textContent ?? ''
}

describe('errorsTableColumns', () => {
    afterEach(cleanup)

    it.each<[string, CellLoads<ErrorFirstSeen>, string]>([
        ['its first seen is not read yet', new Map(), 'was 0'],
        ['its first seen is loading', new Map([['error-1', { status: 'loading' }]]), 'was 0'],
        ['its first seen failed', new Map([['error-1', { status: 'error' }]]), 'was 0'],
        [
            'its first seen says it is not new',
            new Map([['error-1', { status: 'ready', value: { ...READ, isNew: false } }]]),
            'was 0',
        ],
        [
            'its first seen says it is new',
            new Map([['error-1', { status: 'ready', value: { ...READ, isNew: true } }]]),
            'was 0New',
        ],
    ])('shows the served change, with New only from a first seen read that says so: %s', (_name, firstSeen, text) => {
        expect(changeCell(firstSeen)).toBe(text)
    })
})
