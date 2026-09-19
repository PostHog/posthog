import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expectLogic } from 'kea-test-utils'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { initKeaTests } from '~/test/init'
import { ExporterFormat } from '~/types'

import { ExportButton, ExportButtonItem } from './ExportButton'
import { exportsLogic } from './exportsLogic'

jest.mock('lib/utils/accessControlUtils', () => ({
    ...jest.requireActual('lib/utils/accessControlUtils'),
    getAccessControlDisabledReason: jest.fn(() => null),
}))

const CSV_ITEM: ExportButtonItem = { export_format: ExporterFormat.CSV, export_context: { path: '/api/whatever' } }

async function openMenu(items: ExportButtonItem[]): Promise<void> {
    render(<ExportButton items={items} />)
    await userEvent.click(screen.getByText('Export'))
}

describe('ExportButton', () => {
    let logic: ReturnType<typeof exportsLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        logic = exportsLogic()
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it('runs a browser-side handler instead of asking the server to render the file', async () => {
        const onClick = jest.fn()
        await openMenu([{ export_format: ExporterFormat.PNG, onClick }, CSV_ITEM])

        await userEvent.click(screen.getByText('.png'))

        expect(onClick).toHaveBeenCalledTimes(1)
        await expectLogic(logic).toNotHaveDispatchedActions(['startExport'])
    })

    it('still asks the server for a format with no browser-side handler', async () => {
        await openMenu([CSV_ITEM])

        await userEvent.click(screen.getByText('.csv'))

        await expectLogic(logic).toDispatchActions(['startExport'])
    })

    it.each([
        ['only server-rendered formats', false, 'true'],
        ['a browser-rendered format', true, 'false'],
    ])('handles export access when the menu has %s', async (_name, hasBrowserRenderedFormat, exportButtonDisabled) => {
        jest.mocked(getAccessControlDisabledReason).mockReturnValue('You do not have export access')
        const browserRenderedItem: ExportButtonItem = { export_format: ExporterFormat.PNG, onClick: jest.fn() }
        render(<ExportButton items={hasBrowserRenderedFormat ? [browserRenderedItem, CSV_ITEM] : [CSV_ITEM]} />)

        expect(screen.getByText('Export').closest('button')).toHaveAttribute('aria-disabled', exportButtonDisabled)
        if (hasBrowserRenderedFormat) {
            await userEvent.click(screen.getByText('Export'))
            expect(screen.getByText('.csv').closest('button')).toHaveAttribute('aria-disabled', 'true')
            expect(screen.getByText('.png').closest('button')).toHaveAttribute('aria-disabled', 'false')
        }
    })
})
