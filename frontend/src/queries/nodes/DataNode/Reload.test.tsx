import { fireEvent, render, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { Reload } from '~/queries/nodes/DataNode/Reload'
import { ActorsQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

describe('Reload', () => {
    let logic: ReturnType<typeof dataNodeLogic.build>
    const logicProps: DataNodeLogicProps = {
        key: 'reload-test',
        query: { kind: NodeKind.ActorsQuery, select: ['person'] } as ActorsQuery,
    }

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        useMocks({
            post: {
                '/api/environments/:team_id/query/': () =>
                    new Promise<[number, { results: string[] }]>((resolve) =>
                        setTimeout(() => resolve([200, { results: [] }]), 10000)
                    ),
            },
        })
        logic = dataNodeLogic(logicProps)
        logic.mount()
    })

    afterEach(() => logic?.unmount())

    it('cancels only from the cancel control, never from reload', async () => {
        logic.actions.loadData('force_blocking')
        await expectLogic(logic).toMatchValues({ responseLoading: true })

        const { container } = render(
            <BindLogic logic={dataNodeLogic} props={logicProps}>
                <Reload />
            </BindLogic>
        )
        const reload = (): Element | null => container.querySelector('[data-attr="reload-query"]')
        const cancel = (): Element | null => container.querySelector('[data-attr="cancel-query"]')

        expect(reload()?.getAttribute('aria-disabled')).toBe('true')
        expect(cancel()).not.toBeNull()

        fireEvent.click(cancel()!)
        await expectLogic(logic).toMatchValues({ queryCancelled: true })

        await waitFor(() => {
            expect(reload()?.getAttribute('aria-disabled')).not.toBe('true')
            expect(cancel()).toBeNull()
        })
    })

    it('hides cancel while paginating, since that request carries no abort signal', async () => {
        // Own logic with autoLoad off, so the only request in flight is the pagination one.
        const paginatingProps: DataNodeLogicProps = { ...logicProps, key: 'reload-paginating-test', autoLoad: false }
        const paginatingLogic = dataNodeLogic(paginatingProps)
        paginatingLogic.mount()

        paginatingLogic.actions.setResponse({ results: [['person']], hasMore: true } as any)
        paginatingLogic.actions.loadNextData()
        await expectLogic(paginatingLogic).toMatchValues({ responseLoading: true, dataLoading: false })

        const { container } = render(
            <BindLogic logic={dataNodeLogic} props={paginatingProps}>
                <Reload />
            </BindLogic>
        )
        const reload = (): Element | null => container.querySelector('[data-attr="reload-query"]')
        const cancel = (): Element | null => container.querySelector('[data-attr="cancel-query"]')

        expect(reload()?.getAttribute('aria-disabled')).toBe('true')
        expect(cancel()).toBeNull()

        paginatingLogic.unmount()
    })
})
