import { act, cleanup, render, waitFor } from '@testing-library/react'
import { useEffect } from 'react'

import * as retryImportModule from 'lib/utils/retryImport'

import { aiShellLogic } from '~/layout/ai/aiShellLogic'
import { initKeaTests } from '~/test/init'

import { MaxTool } from './MaxTool'
import { useMaxTool } from './useMaxTool'

function TestMaxTool(): null {
    useMaxTool({ identifier: 'read_data', context: { query: 'select 1' } })
    return null
}

// Its own file, so the module-level tool table cache starts empty. Only the last test lets the table load.
describe('useMaxTool before the tool table loads', () => {
    let releaseImports: () => void

    beforeEach(() => {
        initKeaTests()
        const imports = new Promise<void>((resolve) => (releaseImports = resolve))
        jest.spyOn(retryImportModule, 'retryImport').mockImplementation((importFn) => imports.then(importFn))
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('registers the tool with its context at once', () => {
        render(<TestMaxTool />)

        expect(aiShellLogic.values.registeredToolMap.read_data?.context).toEqual({ query: 'select 1' })
    })

    it('keeps the MaxTool children mounted when the tool table arrives', async () => {
        const onMount = jest.fn()
        function Child(): null {
            useEffect(onMount, [])
            return null
        }
        render(
            <MaxTool identifier="read_data" context={{ query: 'select 1' }}>
                <Child />
            </MaxTool>
        )

        act(() => releaseImports())
        await waitFor(() => expect(aiShellLogic.values.registeredToolMap.read_data?.name).toBeTruthy())

        expect(onMount).toHaveBeenCalledTimes(1)
    })
})
