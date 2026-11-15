import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { SupportEditor } from './SupportEditor'

const CONTENT = { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Hello' }] }] }

describe('SupportEditor keyboard shortcuts', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('Cmd+Enter calls the onPressCmdEnter from the latest render', () => {
        const fromFirstRender = jest.fn()
        const fromLatestRender = jest.fn()
        const { rerender, container } = render(
            <Provider>
                <SupportEditor initialContent={CONTENT} onPressCmdEnter={fromFirstRender} />
            </Provider>
        )
        rerender(
            <Provider>
                <SupportEditor initialContent={CONTENT} onPressCmdEnter={fromLatestRender} />
            </Provider>
        )

        fireEvent.keyDown(container.querySelector('.ProseMirror')!, { key: 'Enter', ctrlKey: true })

        expect(fromLatestRender).toHaveBeenCalledTimes(1)
        expect(fromFirstRender).not.toHaveBeenCalled()
    })
})
