import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { QuillSceneStaticName } from './QuillSceneStaticName'

jest.mock('lib/utils/copyToClipboard', () => ({ copyToClipboard: jest.fn() }))

describe('QuillSceneStaticName', () => {
    beforeEach(() => {
        jest.mocked(copyToClipboard).mockResolvedValue(true)
    })

    afterEach(() => {
        cleanup()
        jest.mocked(copyToClipboard).mockReset()
    })

    test.each([
        { label: 'with a description', description: 'Tier request rollout' },
        { label: 'without a description', description: undefined },
    ])('copies a text name on click $label, without a toast', ({ description }) => {
        render(<QuillSceneStaticName name="my-flag-key" description={description} />)

        fireEvent.click(screen.getByText('my-flag-key'))

        expect(copyToClipboard).toHaveBeenCalledWith('my-flag-key', 'name', { silent: true })
    })

    test('confirms the copy in the tooltip, hiding the description', async () => {
        render(<QuillSceneStaticName name="my-flag-key" description="Tier request rollout" />)

        await userEvent.tab()
        expect(await screen.findByText('Click to copy')).toBeInTheDocument()
        await userEvent.click(screen.getByText('my-flag-key'))

        expect(await screen.findByText('Copied')).toBeInTheDocument()
        expect(screen.queryByText('Tier request rollout')).not.toBeInTheDocument()
        expect(screen.queryByText('Click to copy')).not.toBeInTheDocument()
    })

    test('does not confirm a copy that failed', async () => {
        jest.mocked(copyToClipboard).mockResolvedValue(false)
        render(<QuillSceneStaticName name="my-flag-key" />)

        await userEvent.tab()
        await userEvent.click(screen.getByText('my-flag-key'))

        expect(await screen.findByText('Click to copy')).toBeInTheDocument()
        expect(screen.queryByText('Copied')).not.toBeInTheDocument()
    })

    test('does not copy a name that is not plain text', () => {
        render(<QuillSceneStaticName name={<span>Custom name</span>} />)

        fireEvent.click(screen.getByText('Custom name'))

        expect(copyToClipboard).not.toHaveBeenCalled()
    })
})
