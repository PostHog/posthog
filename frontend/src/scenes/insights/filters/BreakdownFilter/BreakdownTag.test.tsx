import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { BreakdownTag } from './BreakdownTag'

describe('BreakdownTag', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        ['remove button', { onClose: jest.fn() }],
        ['options menu', { popover: { overlay: <div>Options</div> } }],
    ])('uses a non-button container with a nested %s', (_name, props) => {
        render(
            <Provider>
                <BreakdownTag breakdown="$browser" breakdownType="event" onClick={jest.fn()} {...props} />
            </Provider>
        )

        expect(screen.getByTestId('breakdown-tag').tagName).toBe('DIV')
    })
})
