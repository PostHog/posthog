import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { resetContext } from 'kea'

import {
    type DotMatrixMockDatum,
    type DotMatrixMockDatasetName,
} from 'lib/components/DotMatrix/examples/dotMatrixMockTypes'
import type { DotMatrixProps } from 'lib/components/DotMatrix/types'

import { AccountDotMatrixTile } from './AccountDotMatrixTile'

jest.mock('lib/components/DotMatrix/DotMatrix', () => {
    const { normalizeDotMatrixData, getDotMatrixCellCount } = jest.requireActual(
        'lib/components/DotMatrix/dotMatrixData'
    )
    return {
        DotMatrix: (props: DotMatrixProps<DotMatrixMockDatum>) => {
            const matrix = normalizeDotMatrixData(props)
            const cell = matrix.getCell(matrix.rows[0].key, matrix.columns[0].key)
            return (
                <>
                    <button data-attr="matrix-selection" onClick={() => props.onSelectedSeriesChange?.(['replay'])}>
                        {props.selectedSeries?.length ? props.selectedSeries.join(',') : 'Select replay'}
                    </button>
                    <span data-attr="matrix-count-label">
                        {typeof props.legend === 'object' ? props.legend.countLabel : ''}
                    </span>
                    <span data-attr="matrix-count">{getDotMatrixCellCount(cell, props)}</span>
                    <span data-attr="matrix-scale">{props.countScale?.[0].color}</span>
                    {props.renderTooltip?.(cell)}
                </>
            )
        },
    }
})

describe('AccountDotMatrixTile', () => {
    beforeEach(() => resetContext())
    afterEach(cleanup)

    it('keeps identically named document tiles independent across mounted account views', () => {
        const firstSave = jest.fn()
        const secondSave = jest.fn()
        render(
            <>
                <AccountDotMatrixTile instanceId="same-document-node:0" onConfigChange={firstSave} />
                <AccountDotMatrixTile instanceId="same-document-node:0" onConfigChange={secondSave} />
            </>
        )
        fireEvent.click(screen.getAllByTestId('matrix-selection')[0])
        expect(firstSave).toHaveBeenLastCalledWith({ dataset: 'people', mode: 'dots', selectedSeries: ['replay'] })
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
                instanceId="saved-tile"
                initialConfig={{ selectedSeries: ['replay'] }}
                onConfigChange={onConfigChange}
            />
        )
        expect(screen.getByTestId('matrix-selection').textContent).toBe('replay')
        rerender(
            <AccountDotMatrixTile
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
            <AccountDotMatrixTile instanceId="readonly-tile" initialConfig={{ selectedSeries: [] }} />
        )
        fireEvent.click(screen.getByTestId('matrix-selection'))
        expect(screen.getByTestId('matrix-selection').textContent).toBe('replay')
        rerender(
            <AccountDotMatrixTile
                instanceId="readonly-tile"
                initialConfig={{ dataset: 'people', mode: 'dots', selectedSeries: [] }}
            />
        )
        expect(screen.getByTestId('matrix-selection').textContent).toBe('replay')
    })

    it.each<{
        dataset: DotMatrixMockDatasetName
        selectedSeries: string[]
        count: number
        label: string
        scale: string
    }>([
        { dataset: 'product_activity', selectedSeries: [], count: 9, label: 'Products used', scale: 'green' },
        {
            dataset: 'product_activity',
            selectedSeries: ['pa'],
            count: 12,
            label: 'Users of Product analytics',
            scale: 'blue',
        },
        {
            dataset: 'product_activity',
            selectedSeries: ['pa', 'web', 'surveys'],
            count: 12,
            label: 'Users of any of these 3 products',
            scale: 'blue',
        },
        { dataset: 'people', selectedSeries: ['pa'], count: 1, label: 'Users of Product analytics', scale: 'blue' },
        { dataset: 'ci', selectedSeries: ['job-1', 'job-3'], count: 2, label: 'Failing jobs', scale: 'green' },
    ])(
        'keeps $dataset count, label, and scale consistent for $selectedSeries',
        ({ dataset, selectedSeries, count, label, scale }) => {
            render(<AccountDotMatrixTile initialConfig={{ dataset, mode: 'count', selectedSeries }} />)
            expect(screen.getByTestId('matrix-count').textContent).toBe(String(count))
            expect(screen.getByTestId('matrix-count-label').textContent).toBe(label)
            expect(screen.getByTestId('matrix-scale').textContent).toBe(`var(--dot-matrix-demo-${scale}-1)`)
            expect(screen.queryByText('Distinct users') !== null).toBe(dataset !== 'ci' && selectedSeries.length > 0)
        }
    )
})
