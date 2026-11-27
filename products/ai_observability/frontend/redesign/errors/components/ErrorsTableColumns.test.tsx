import { cleanup, fireEvent, render } from '@testing-library/react'

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
                onOpen: () => {},
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

    it('opens an error from a button on its message, which a keyboard reaches, and not from its row as well', () => {
        initKeaTests()
        const onOpen = jest.fn()
        const onRow = jest.fn()
        const item = makeErrorListItem({ key: 'error-1', message: 'TimeoutError: took too long' })
        const { getByText } = render(
            <LemonTable<ErrorListItemApi>
                columns={errorsTableColumns({
                    maxOccurrences: 128,
                    order: 'occurrences',
                    onOrder: () => {},
                    onOpen,
                    firstSeen: new Map(),
                    timezone: 'UTC',
                    'data-attr': 'errors-list',
                })}
                dataSource={[item]}
                rowKey={(row) => row.key}
                onRow={() => ({ onClick: onRow })}
            />
        )

        const message = getByText('TimeoutError: took too long')
        expect(message.closest('button')).toBeInstanceOf(HTMLButtonElement)
        fireEvent.click(message)

        expect(onOpen).toHaveBeenCalledWith(item)
        expect(onRow).not.toHaveBeenCalled()
    })
})
