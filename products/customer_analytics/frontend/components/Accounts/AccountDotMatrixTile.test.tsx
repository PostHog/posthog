import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { resetContext } from 'kea'

import { AccountDotMatrixTile } from './AccountDotMatrixTile'

jest.mock('lib/components/DotMatrix/DotMatrix', () => ({
    DotMatrix: ({
        selectedSeries,
        onSelectedSeriesChange,
    }: {
        selectedSeries: string[]
        onSelectedSeriesChange: (keys: string[]) => void
    }) => (
        <button data-attr="matrix-selection" onClick={() => onSelectedSeriesChange(['replay'])}>
            {selectedSeries.length ? selectedSeries.join(',') : 'Select replay'}
        </button>
    ),
}))

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
})
