import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { QuillSceneStaticName } from './QuillSceneStaticName'

jest.mock('lib/utils/copyToClipboard', () => ({ copyToClipboard: jest.fn() }))

describe('QuillSceneStaticName', () => {
    afterEach(() => {
        cleanup()
        jest.mocked(copyToClipboard).mockClear()
    })

    test.each([
        { label: 'with a description', description: 'Tier request rollout' },
        { label: 'without a description', description: undefined },
    ])('copies a text name on click $label', ({ description }) => {
        render(<QuillSceneStaticName name="my-flag-key" description={description} />)

        fireEvent.click(screen.getByText('my-flag-key'))

        expect(copyToClipboard).toHaveBeenCalledWith('my-flag-key', 'name')
    })

    test('does not copy a name that is not plain text', () => {
        render(<QuillSceneStaticName name={<span>Custom name</span>} />)

        fireEvent.click(screen.getByText('Custom name'))

        expect(copyToClipboard).not.toHaveBeenCalled()
    })
})
