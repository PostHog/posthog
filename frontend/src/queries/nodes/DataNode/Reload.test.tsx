import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { Reload } from '~/queries/nodes/DataNode/Reload'
import { performQuery } from '~/queries/query'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

jest.mock('~/queries/query', () => ({
    ...jest.requireActual('~/queries/query'),
    performQuery: jest.fn(),
}))

describe('Reload', () => {
    let logic: ReturnType<typeof dataNodeLogic.build>
    let releaseQuery: () => void

    const props = {
        key: 'reload-test',
        query: { kind: NodeKind.HogQLQuery, query: 'select * from events' },
    } as const

    const button = (): HTMLElement => screen.getByRole('button')

    beforeEach(() => {
        initKeaTests()
        ;(performQuery as jest.Mock).mockImplementation(
            async () =>
                await new Promise((resolve) => {
                    releaseQuery = () => resolve({ results: [['a result']] })
                })
        )
        logic = dataNodeLogic(props)
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic?.unmount()
    })

    it('does not cancel the first load, and cancels a reload', async () => {
        const user = userEvent.setup()
        render(
            <BindLogic logic={dataNodeLogic} props={props}>
                <Reload />
            </BindLogic>
        )

        logic.actions.loadData('force_blocking')
        await waitFor(() => expect(button()).toHaveAttribute('aria-disabled', 'true'))
        expect(button()).toHaveTextContent('Reload')

        await user.click(button())
        expect(logic.values.queryCancelled).toBe(false)
        expect(logic.values.responseLoading).toBe(true)

        releaseQuery()
        await waitFor(() => expect(button()).toHaveAttribute('aria-disabled', 'false'))

        logic.actions.loadData('force_blocking')
        await waitFor(() => expect(button()).toHaveTextContent('Cancel'))
        await user.click(button())
        expect(logic.values.queryCancelled).toBe(true)
    })
})
