import '@testing-library/jest-dom'

import { act, cleanup, render } from '@testing-library/react'

import { preflightLogic } from 'lib/logic/preflightLogic'

import { initKeaTests } from '~/test/init'

import { supportLogic } from './supportLogic'
import { SupportModal } from './SupportModal'

describe('SupportModal', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    test('does not self-destruct while preflight is still loading', () => {
        const onAfterClose = jest.fn()

        render(<SupportModal onAfterClose={onAfterClose} />)

        expect(onAfterClose).not.toHaveBeenCalled()
    })

    test('self-destructs once preflight resolves to a self-hosted, non-debug instance', () => {
        const onAfterClose = jest.fn()

        render(<SupportModal onAfterClose={onAfterClose} />)
        act(() => {
            preflightLogic.actions.loadPreflightSuccess({ cloud: false, is_debug: false } as any)
        })

        expect(onAfterClose).toHaveBeenCalledTimes(1)
    })

    test('stays mounted once preflight resolves to a cloud/dev instance', async () => {
        const onAfterClose = jest.fn()

        const { findAllByTestId } = render(<SupportModal onAfterClose={onAfterClose} />)
        act(() => {
            preflightLogic.actions.loadPreflightSuccess({ cloud: true } as any)
            // The modal only ever mounts via openSupportForm, which opens it in the same act - mirror that.
            supportLogic.actions.openSupportForm({})
        })

        // react-modal mounts its portal content on a follow-up effect flush
        expect(await findAllByTestId('submit')).not.toHaveLength(0)
        expect(onAfterClose).not.toHaveBeenCalled()
    })
})
