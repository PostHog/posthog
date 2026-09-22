import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expectLogic } from 'kea-test-utils'
import { type ReactNode } from 'react'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { ScreenShotEditor } from 'lib/components/TakeScreenshot/ScreenShotEditor'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { downloadFile } from 'lib/utils/dom'

import { initKeaTests } from '~/test/init'
import { ExporterFormat } from '~/types'

import { captureImageLogic } from './captureImageLogic'
import { SceneExportDropdownMenu } from './SceneExportDropdownMenu'

jest.mock('html-to-image', () => ({
    toBlob: jest.fn(() => Promise.resolve(new Blob(['png'], { type: 'image/png' }))),
}))
jest.mock('lib/utils/accessControlUtils', () => ({
    ...jest.requireActual('lib/utils/accessControlUtils'),
    getAccessControlDisabledReason: jest.fn(() => null),
}))
jest.mock('lib/utils/dom', () => ({
    ...jest.requireActual('lib/utils/dom'),
    downloadFile: jest.fn(),
}))

// Radix relies on pointer events that jsdom does not implement, so the menu renders inline here.
jest.mock('lib/ui/DropdownMenu/DropdownMenu', () => ({
    DropdownMenu: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    DropdownMenuContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    DropdownMenuGroup: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    DropdownMenuItem: ({ children, onClick }: { children: ReactNode; onClick?: () => void }) => (
        <div onClick={onClick}>{children}</div>
    ),
    DropdownMenuTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

const CSV_ITEM = { format: ExporterFormat.CSV, dataAttr: 'export-csv', context: { path: '/api/whatever' } }

describe('SceneExportDropdownMenu', () => {
    let logic: ReturnType<typeof exportsLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        logic = exportsLogic()
        logic.mount()
        captureImageLogic.mount()
    })

    afterEach(() => {
        cleanup()
        captureImageLogic.unmount()
        logic.unmount()
    })

    it('runs a browser-side handler instead of asking the server to render the file', async () => {
        const onClick = jest.fn()
        render(
            <SceneExportDropdownMenu
                dropdownMenuItems={[{ format: ExporterFormat.PNG, dataAttr: 'export-png', onClick }, CSV_ITEM]}
            />
        )

        await userEvent.click(screen.getByText('.png'))

        expect(onClick).toHaveBeenCalledTimes(1)
        await expectLogic(logic).toNotHaveDispatchedActions(['startExport'])
    })

    it('still asks the server for a format with no browser-side handler', async () => {
        render(<SceneExportDropdownMenu dropdownMenuItems={[CSV_ITEM]} />)

        await userEvent.click(screen.getByText('.csv'))

        await expectLogic(logic).toDispatchActions(['startExport'])
    })

    it('downloads the browser-rendered PNG in one click, without opening the editor', async () => {
        const target = { selector: '[data-attr="insights-graph"]', screenshotKey: 'test', name: 'Weekly pageviews' }
        render(
            <>
                <div data-attr="insights-graph">chart</div>
                <SceneExportDropdownMenu
                    dropdownMenuItems={[
                        {
                            format: ExporterFormat.PNG,
                            dataAttr: 'export-png',
                            onClick: () => captureImageLogic.actions.downloadImage(target),
                        },
                    ]}
                />
                <ScreenShotEditor screenshotKey={target.screenshotKey} />
            </>
        )

        await userEvent.click(screen.getByText('.png'))

        await waitFor(() => expect(downloadFile).toHaveBeenCalledTimes(1))
        expect(jest.mocked(downloadFile).mock.calls[0][0].name).toBe('weekly-pageviews.png')
        expect(screen.queryByText('Edit Screenshot')).not.toBeInTheDocument()
    })

    it.each([
        ['only server-rendered formats', false, true],
        ['a browser-rendered format', true, false],
    ])('handles export access when the menu has %s', (_name, hasBrowserRenderedFormat, exportMenuDisabled) => {
        jest.mocked(getAccessControlDisabledReason).mockReturnValue('You do not have export access')
        const onClick = jest.fn()
        const browserRenderedItem = {
            format: ExporterFormat.PNG,
            dataAttr: 'export-png',
            onClick,
        }
        render(
            <SceneExportDropdownMenu
                dropdownMenuItems={hasBrowserRenderedFormat ? [browserRenderedItem, CSV_ITEM] : [CSV_ITEM]}
            />
        )

        expect(screen.getByText('Export')).toHaveProperty('disabled', exportMenuDisabled)
        expect(screen.getByText('.csv')).toBeDisabled()
        if (hasBrowserRenderedFormat) {
            expect(screen.getByText('.png')).toBeEnabled()
        }
    })
})
