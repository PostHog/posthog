import { cleanup, fireEvent, render } from '@testing-library/react'

import { LemonTable } from 'lib/lemon-ui/LemonTable'

import { initKeaTests } from '~/test/init'

import type { ToolListItemApi } from '../../../generated/api.schemas'
import { makeToolListItem } from '../testFixtures'
import { toolsTableColumns } from './ToolsTableColumns'

describe('toolsTableColumns', () => {
    afterEach(cleanup)

    it('opens a tool from a button on its name, which a keyboard reaches, and not from its row as well', () => {
        initKeaTests()
        const onOpen = jest.fn()
        const onRow = jest.fn()
        const item = makeToolListItem({ key: 'tool-1', name: 'search_orders' })
        const { getByText } = render(
            <LemonTable<ToolListItemApi>
                columns={toolsTableColumns({
                    maxCalls: 10,
                    order: 'calls',
                    onOrder: () => {},
                    onOpen,
                    traceShares: new Map(),
                    'data-attr': 'tools-list',
                })}
                dataSource={[item]}
                rowKey={(row) => row.key}
                onRow={() => ({ onClick: onRow })}
            />
        )

        const name = getByText('search_orders')
        expect(name.closest('button')).toBeInstanceOf(HTMLButtonElement)
        fireEvent.click(name)

        expect(onOpen).toHaveBeenCalledWith(item)
        expect(onRow).not.toHaveBeenCalled()
    })
})
