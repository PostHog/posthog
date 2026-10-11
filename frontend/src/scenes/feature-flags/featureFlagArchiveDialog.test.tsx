import { fireEvent, render } from '@testing-library/react'

import { LemonDialog } from '@posthog/lemon-ui'

import { initKeaTests } from '~/test/init'

import { openFeatureFlagArchiveDialog } from './featureFlagArchiveDialog'

describe('openFeatureFlagArchiveDialog', () => {
    it('submits only once while the dialog is closing', () => {
        initKeaTests()
        const archive = jest.fn()
        const close = jest.fn()
        const open = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
        openFeatureFlagArchiveDialog({ id: 1, key: 'example-flag', active: false, filters: { groups: [] } }, archive)
        const { content } = open.mock.calls[0][0]
        const { getByText } = render(typeof content === 'function' ? content(close) : content)

        fireEvent.click(getByText('Archive'))
        fireEvent.click(getByText('Archive'))

        expect(archive).toHaveBeenCalledTimes(1)
        expect(close).toHaveBeenCalledTimes(1)
    })
})
