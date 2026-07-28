import { render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import {
    externalDataSourcesConnectionsList,
    externalDataSourcesDirectConnectionOptionsList,
} from 'products/warehouse_sources/frontend/generated/api'

import { ConnectionSelector } from './ConnectionSelector'
import { connectionSelectorLogic } from './connectionSelectorLogic'

// endpointLogic uses permanentlyMount() with a keyed logic, which crashes in
// tests without the full React component tree — disable auto-mounting
jest.mock('lib/utils/kea-logic-builders', () => ({
    permanentlyMount: () => () => {},
}))

jest.mock('products/warehouse_sources/frontend/generated/api', () => ({
    externalDataSourcesConnectionsList: jest.fn(),
    externalDataSourcesDirectConnectionOptionsList: jest.fn(),
}))

const mockConnectionsList = externalDataSourcesConnectionsList as jest.Mock
const mockDirectConnectionOptionsList = externalDataSourcesDirectConnectionOptionsList as jest.Mock

describe('ConnectionSelector', () => {
    beforeEach(() => {
        initKeaTests()
        mockConnectionsList.mockReset().mockResolvedValue([])
        mockDirectConnectionOptionsList.mockReset().mockResolvedValue([])
        connectionSelectorLogic().mount()
    })

    // A long source name (e.g. "managed_warehouse (DuckDB)") used to wrap onto a second line and
    // spill out of the narrow database-tree sidebar, over the neighbouring toolbar.
    it('truncates a long connection name instead of wrapping or overflowing the sidebar', () => {
        const { container } = render(<ConnectionSelector tabId="test-tab" />)

        const button = container.querySelector('.LemonSelect')
        // Without min-w-0 the flex item refuses to shrink below the label's min-content width.
        expect(button?.classList.contains('min-w-0')).toBe(true)

        const label = button?.querySelector('.LemonButton__content > span')
        expect(label?.classList.contains('overflow-hidden')).toBe(true)
        expect(label?.classList.contains('text-ellipsis')).toBe(true)
        expect(label?.classList.contains('whitespace-nowrap')).toBe(true)
    })
})
