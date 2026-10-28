import '@testing-library/jest-dom'

import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { openOverwriteMetricDialog } from './openOverwriteMetricDialog'

const TITLE = 'Overwrite the existing metric?'

describe('openOverwriteMetricDialog', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        [
            'the close icon',
            1,
            0,
            async (): Promise<void> => void fireEvent.click(await screen.findByLabelText('close')),
        ],
        ['Overwrite', 0, 1, async (): Promise<void> => void fireEvent.click(await screen.findByText('Overwrite'))],
        ['navigation', 0, 0, async (): Promise<void> => router.actions.push('/elsewhere')],
    ])('closed by %s: runs onCancel %i times and onOverwrite %i times', async (_how, cancels, overwrites, close) => {
        const onOverwrite = jest.fn()
        const onCancel = jest.fn()
        openOverwriteMetricDialog({ existing: { name: 'mrr', status: 'approved' }, onOverwrite, onCancel })
        await screen.findByText(TITLE)

        await close()
        await waitFor(() => expect(screen.queryByText(TITLE)).not.toBeInTheDocument())

        expect(onCancel).toHaveBeenCalledTimes(cancels)
        expect(onOverwrite).toHaveBeenCalledTimes(overwrites)
    })
})
