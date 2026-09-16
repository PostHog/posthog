import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { ExporterFormat } from '~/types'

import { ExportColumnsModal } from './ExportColumnsModal'

jest.mock('posthog-js', () => ({ __esModule: true, default: { capture: jest.fn() } }))

describe('ExportColumnsModal', () => {
    afterEach(() => cleanup())

    const columns = [{ name: 'event' }, { name: 'timestamp' }, { name: 'properties.$browser', label: 'Browser' }]

    const renderModal = (): jest.Mock => {
        const onExport = jest.fn()
        render(
            <ExportColumnsModal
                isOpen
                columns={columns}
                formats={[ExporterFormat.CSV, ExporterFormat.XLSX]}
                onClose={jest.fn()}
                onExport={onExport}
            />
        )
        return onExport
    }

    it('exports the columns that are left checked, in table order', () => {
        const onExport = renderModal()

        fireEvent.click(screen.getByText('timestamp'))
        fireEvent.click(screen.getByText('Export .csv'))

        expect(onExport).toHaveBeenCalledWith(ExporterFormat.CSV, ['event', 'properties.$browser'])
    })

    it('exports every column when nothing is unchecked', () => {
        const onExport = renderModal()

        fireEvent.click(screen.getByText('Export .xlsx'))

        expect(onExport).toHaveBeenCalledWith(ExporterFormat.XLSX, ['event', 'timestamp', 'properties.$browser'])
    })

    it('cannot export an empty column list', () => {
        const onExport = renderModal()

        fireEvent.click(screen.getByText('Clear all'))
        fireEvent.click(screen.getByText('Export .csv'))

        expect(onExport).not.toHaveBeenCalled()
    })
})
