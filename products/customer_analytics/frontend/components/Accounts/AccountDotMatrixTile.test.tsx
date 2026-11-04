import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import type { DotMatrixProps } from 'lib/components/DotMatrix/types'

import { performQuery } from '~/queries/query'
import type { AccountActivityMatrixResult } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import type { AccountActivityMatrixDatum } from './accountActivityMatrix'
import { EMPTY_ACCOUNT_ACTIVITY_MATRIX } from './accountActivityMatrix'
import { AccountDotMatrixTile } from './AccountDotMatrixTile'

jest.mock('~/queries/query', () => ({ performQuery: jest.fn() }))
const mockPerformQuery = performQuery as jest.Mock

jest.mock('lib/components/DotMatrix/DotMatrix', () => ({
    DotMatrix: (props: DotMatrixProps<AccountActivityMatrixDatum>) => (
        <>
            <button data-attr="matrix-selection" onClick={() => props.onSelectedSeriesChange?.(['replay'])}>
                {props.selectedSeries?.length ? props.selectedSeries.join(',') : 'Select replay'}
            </button>
            {!props.loading && !props.rows?.length ? <span data-attr="matrix-empty">{props.emptyState}</span> : null}
        </>
    ),
}))

jest.mock('lib/monaco/CodeEditor', () => ({ CodeEditor: () => <div data-attr="matrix-code-editor" /> }))

const WITH_SERIES: AccountActivityMatrixResult = {
    ...EMPTY_ACCOUNT_ACTIVITY_MATRIX,
    series: [
        { key: 'pa', label: 'Insights' },
        { key: 'replay', label: 'Replay' },
    ],
}

describe('AccountDotMatrixTile', () => {
    beforeEach(() => {
        initKeaTests()
        mockPerformQuery.mockReset()
        mockPerformQuery.mockResolvedValue({ results: WITH_SERIES })
    })
    afterEach(cleanup)

    it('keeps identically named document tiles independent across mounted account views', () => {
        const firstSave = jest.fn()
        const secondSave = jest.fn()
        render(
            <>
                <AccountDotMatrixTile accountId="account-1" instanceId="same-node:0" onConfigChange={firstSave} />
                <AccountDotMatrixTile accountId="account-1" instanceId="same-node:0" onConfigChange={secondSave} />
            </>
        )
        fireEvent.click(screen.getAllByTestId('matrix-selection')[0])
        expect(firstSave).not.toHaveBeenCalled()
        expect(secondSave).not.toHaveBeenCalled()
        expect(screen.getAllByTestId('matrix-selection').map((button) => button.textContent)).toEqual([
            'replay',
            'Select replay',
        ])
    })

    it('restores changed parent config without writing it back', () => {
        const onConfigChange = jest.fn()
        const { rerender } = render(
            <AccountDotMatrixTile
                accountId="account-1"
                instanceId="saved-tile"
                initialConfig={{ selectedSeries: ['replay'] }}
                onConfigChange={onConfigChange}
            />
        )
        expect(screen.getByTestId('matrix-selection').textContent).toBe('replay')
        rerender(
            <AccountDotMatrixTile
                accountId="account-1"
                instanceId="saved-tile"
                initialConfig={{ selectedSeries: ['pa'] }}
                onConfigChange={onConfigChange}
            />
        )
        expect(screen.getByTestId('matrix-selection').textContent).toBe('pa')
        expect(onConfigChange).not.toHaveBeenCalled()
    })

    it('retains readonly exploration when an unchanged saved config gets a new object', () => {
        const { rerender } = render(
            <AccountDotMatrixTile
                accountId="account-1"
                instanceId="readonly-tile"
                initialConfig={{ selectedSeries: [] }}
            />
        )
        fireEvent.click(screen.getByTestId('matrix-selection'))
        expect(screen.getByTestId('matrix-selection').textContent).toBe('replay')
        rerender(
            <AccountDotMatrixTile
                accountId="account-1"
                instanceId="readonly-tile"
                initialConfig={{ mode: 'dots', weeks: 8, selectedSeries: [] }}
            />
        )
        expect(screen.getByTestId('matrix-selection').textContent).toBe('replay')
    })

    it.each<{ name: string; response: () => Promise<unknown>; text: string }>([
        {
            name: 'no usage metrics',
            response: () => Promise.resolve({ results: { ...WITH_SERIES, emptyReason: 'no_metrics' } }),
            text: 'Add a usage metric in project settings to see activity here.',
        },
        {
            name: 'no account group type',
            response: () => Promise.resolve({ results: { ...WITH_SERIES, emptyReason: 'no_group_type' } }),
            text: 'Choose an account group type in Customer analytics settings to see activity here.',
        },
        {
            name: 'no linked activity',
            response: () => Promise.resolve({ results: { ...WITH_SERIES, emptyReason: 'no_external_id' } }),
            text: "This account isn't linked to any activity yet.",
        },
        {
            name: 'no activity in the window',
            response: () => Promise.resolve({ results: WITH_SERIES }),
            text: 'No activity for this account in the last 8 weeks.',
        },
        {
            name: 'a failed request',
            response: () => Promise.reject(Object.assign(new Error('boom'), { status: 500 })),
            text: "Couldn't load activity for this account.",
        },
    ])('tells the viewer what to do next for $name', async ({ response, text }) => {
        mockPerformQuery.mockImplementation(response)
        render(<AccountDotMatrixTile accountId="account-1" instanceId="state-tile" />)
        expect(await screen.findByText(text)).toBeTruthy()
    })

    it('shows Cancel, not Edit query, while editing and returns to saved results on Cancel', async () => {
        mockPerformQuery.mockResolvedValue({ columns: ['r', 'c'], results: [['saved', 1]] })
        const onConfigChange = jest.fn()
        render(
            <AccountDotMatrixTile
                accountId="account-1"
                instanceId="edit-tile"
                initialConfig={{ source: { kind: 'hogql', query: 'SELECT 1', mapping: { row: 'r', column: 'c' } } }}
                onConfigChange={onConfigChange}
            />
        )
        fireEvent.click(await screen.findByRole('button', { name: 'Edit query' }))
        expect(screen.queryByRole('button', { name: 'Edit query' })).toBeNull()
        expect(await screen.findByTestId('matrix-code-editor')).toBeTruthy()

        fireEvent.click(screen.getByTestId('dot-matrix-cancel-query'))
        expect(screen.queryByTestId('account-dot-matrix-query-editor')).toBeNull()
        expect(screen.getByRole('button', { name: 'Edit query' })).toBeTruthy()
        expect(onConfigChange).not.toHaveBeenCalled()
    })
})
