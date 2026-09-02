import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ToastContainer } from 'react-toastify'

import { ScreenShotEditor } from 'lib/components/TakeScreenshot/ScreenShotEditor'

import { initKeaTests } from '~/test/init'

import { SceneCopyImageButton } from './SceneCopyImageButton'

jest.mock('html-to-image', () => ({
    toBlob: jest.fn(() => Promise.resolve(new Blob(['png'], { type: 'image/png' }))),
}))

const TARGET = { selector: '[data-attr="insights-graph"]', screenshotKey: 'test' }

function renderButton(): void {
    render(
        <>
            <div data-attr="insights-graph">chart</div>
            <SceneCopyImageButton target={TARGET} dataAttrKey="insight" />
            <ScreenShotEditor screenshotKey={TARGET.screenshotKey} />
            <ToastContainer />
        </>
    )
}

describe('SceneCopyImageButton', () => {
    let write: jest.Mock

    beforeEach(() => {
        initKeaTests()

        write = jest.fn(() => Promise.resolve())
        Object.defineProperty(navigator, 'clipboard', { value: { write }, configurable: true })
        ;(global as any).ClipboardItem = jest.fn((items) => items)
    })

    afterEach(() => {
        cleanup()
        delete (global as any).ClipboardItem
    })

    it('says the image is on the clipboard and offers the screenshot editor', async () => {
        renderButton()

        await userEvent.click(screen.getByText('Copy as PNG'))

        expect(await screen.findByText('Image copied to clipboard')).toBeInTheDocument()
        expect(write).toHaveBeenCalledTimes(1)

        await userEvent.click(screen.getByText('Edit image'))

        expect(await screen.findByText('Edit Screenshot')).toBeInTheDocument()
    })

    it('points at Export when the clipboard write fails, and stays clickable', async () => {
        write.mockRejectedValueOnce(new Error('denied'))
        renderButton()

        await userEvent.click(screen.getByText('Copy as PNG'))

        expect(await screen.findByText(/Could not copy the image/)).toBeInTheDocument()
        expect(screen.getByText('Copy as PNG')).toBeEnabled()
    })

    it('reports a browser that cannot put images on the clipboard', async () => {
        delete (global as any).ClipboardItem
        renderButton()

        await userEvent.click(screen.getByText('Copy as PNG'))

        expect(await screen.findByText(/This browser cannot copy images/)).toBeInTheDocument()
        expect(write).not.toHaveBeenCalled()
    })

    it('captures nothing while a disabled reason holds', async () => {
        render(
            <>
                <div data-attr="insights-graph">chart</div>
                <SceneCopyImageButton
                    target={TARGET}
                    dataAttrKey="insight"
                    disabledReasons={{ 'Wait for the insight to finish loading': true }}
                />
            </>
        )

        const button = screen.getByText('Copy as PNG')
        expect(button).toBeDisabled()

        await userEvent.click(button)

        expect(write).not.toHaveBeenCalled()
    })

    it('reports a missing target instead of copying an empty image', async () => {
        render(
            <>
                <SceneCopyImageButton target={TARGET} dataAttrKey="insight" />
                <ToastContainer />
            </>
        )

        await userEvent.click(screen.getByText('Copy as PNG'))

        expect(await screen.findByText(/Could not find anything to capture/)).toBeInTheDocument()
        expect(write).not.toHaveBeenCalled()
    })
})
