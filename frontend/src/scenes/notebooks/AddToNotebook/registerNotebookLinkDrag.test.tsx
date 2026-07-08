import { fireEvent, render } from '@testing-library/react'

import { Link } from 'lib/lemon-ui/Link'

import { initKeaTests } from '~/test/init'

import { registerNotebookLinkDrag } from './registerNotebookLinkDrag'

describe('registerNotebookLinkDrag', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('wires notebook drag into Link so dragging an internal link carries its url', () => {
        registerNotebookLinkDrag()
        const { container } = render(<Link to="/insights">Insights</Link>)
        const anchor = container.querySelector('a')
        expect(anchor).toBeTruthy()

        const dataTransfer = { setData: jest.fn() }
        fireEvent.dragStart(anchor!, { dataTransfer })

        expect(dataTransfer.setData).toHaveBeenCalledWith('text/uri-list', `${window.location.origin}/insights`)
    })
})
