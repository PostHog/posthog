import { cleanup, render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { maxGlobalLogic } from './maxGlobalLogic'
import { useMaxTool } from './useMaxTool'

function TestMaxTool({ context, active = true }: { context: Record<string, unknown>; active?: boolean }): null {
    useMaxTool({
        identifier: 'read_data',
        context,
        active,
    })

    return null
}

describe('useMaxTool', () => {
    let logic: ReturnType<typeof maxGlobalLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = maxGlobalLogic()
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('updates the registered tool context without deregistering between updates', () => {
        const deregisterTool = jest.spyOn(logic.actions, 'deregisterTool')
        const { rerender, unmount } = render(<TestMaxTool context={{ query: 'select 1' }} />)

        expect(logic.values.registeredToolMap.read_data?.context).toEqual({ query: 'select 1' })

        rerender(<TestMaxTool context={{ query: 'select 2' }} />)

        expect(logic.values.registeredToolMap.read_data?.context).toEqual({ query: 'select 2' })
        expect(deregisterTool).not.toHaveBeenCalled()

        unmount()

        expect(deregisterTool).toHaveBeenCalledWith('read_data')
    })
})
