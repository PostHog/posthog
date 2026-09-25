import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { RowDetailsModal } from './RowDetailsModal'

jest.mock('lib/utils/copyToClipboard', () => ({
    copyToClipboard: jest.fn(() => Promise.resolve(true)),
}))

const JSON_STRING = '{"$browser":"Chrome","pages":1}'

describe('RowDetailsModal', () => {
    beforeEach(() => {
        jest.mocked(copyToClipboard).mockClear()
    })

    afterEach(() => {
        cleanup()
    })

    // The raw view and the copy button must agree on one text form of the cell. A JSON string is
    // already raw text, so stringifying it escapes every quote; an object needs stringifying, or it
    // renders as "[object Object]".
    it.each([
        ['a JSON string keeps its own text', JSON_STRING, JSON_STRING],
        ['an object is pretty printed', { a: 1, b: [2, 3] }, JSON.stringify({ a: 1, b: [2, 3] }, null, 2)],
        ['an array is pretty printed', [1, 2, 3], JSON.stringify([1, 2, 3], null, 2)],
    ])('%s', async (_label, value, expectedRaw) => {
        const { container } = render(
            <RowDetailsModal isOpen onClose={jest.fn()} columns={['properties']} values={[value]} />
        )

        await userEvent.click(screen.getByLabelText('Show raw'))
        expect(container.ownerDocument.querySelector('pre')?.textContent).toBe(expectedRaw)

        await userEvent.click(screen.getByLabelText('Copy value'))
        expect(copyToClipboard).toHaveBeenCalledWith(expectedRaw, 'value')
    })
})
