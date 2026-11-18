import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'

import { MarkdownNotebookEntityPicker } from './MarkdownNotebookEntityPicker'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('MarkdownNotebookEntityPicker', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team/dashboards/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [{ id: 1, name: 'Workflows', pinned: false }],
                },
            },
        })
        initKeaTests()
        groupsModel.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it('loads dashboards in the notebook dashboard picker', async () => {
        render(
            <Provider>
                <MarkdownNotebookEntityPicker action="add" kind="dashboard" onClose={jest.fn()} onSelect={jest.fn()} />
            </Provider>
        )

        expect(await screen.findByText('Workflows')).toBeInTheDocument()
    })
})
