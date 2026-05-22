import { cleanup, fireEvent, render, within } from '@testing-library/react'

import { LemonMenuItem } from '@posthog/lemon-ui'

import { queryByDataAttr } from '~/test/byDataAttr'

import { TileId } from './common'
import { WebTileHeader } from './WebTileHeader'

const noopMenuItems: LemonMenuItem[] = [
    { label: 'Copy', items: [{ label: 'Link', onClick: () => {} }] },
    { label: 'Show more', onClick: () => {} },
]

describe('WebTileHeader', () => {
    afterEach(() => {
        cleanup()
    })

    test('renders a plain title (no dropdown)', () => {
        const { container } = render(
            <WebTileHeader tileId={TileId.RETENTION} title="Retention" overflowMenuItems={noopMenuItems} />
        )
        expect(within(container).getByText('Retention')).toBeTruthy()
    })

    test('always renders the overflow menu trigger with a tile-scoped data-attr', () => {
        const { container } = render(<WebTileHeader tileId={TileId.GRAPHS} overflowMenuItems={noopMenuItems} />)
        expect(queryByDataAttr(container, 'web-analytics-tile-overflow-GRAPHS')).toBeTruthy()
    })

    test('renders the title dropdown when titleDropdown is provided', () => {
        const onChange = jest.fn()
        const { container } = render(
            <WebTileHeader
                tileId={TileId.PATHS}
                titleDropdown={{
                    value: 'a',
                    options: [
                        { value: 'a', label: 'Paths' },
                        { value: 'b', label: 'Entry paths' },
                    ],
                    onChange,
                }}
                overflowMenuItems={noopMenuItems}
            />
        )
        expect(queryByDataAttr(container, 'web-analytics-title-dropdown-PATHS')).toBeTruthy()
    })

    test('renders the title prefix before the dropdown when both are provided', () => {
        const onChange = jest.fn()
        const { container } = render(
            <WebTileHeader
                tileId={TileId.SOURCES}
                titlePrefix="Sources by"
                titleDropdown={{
                    value: 'channel',
                    options: [
                        { value: 'channel', label: 'Channel' },
                        { value: 'utm_source', label: 'UTM Source' },
                    ],
                    onChange,
                }}
                overflowMenuItems={noopMenuItems}
            />
        )
        expect(within(container).getByText('Sources by')).toBeTruthy()
        expect(queryByDataAttr(container, 'web-analytics-title-dropdown-SOURCES')).toBeTruthy()
    })

    test('renders no title nor dropdown when none provided', () => {
        const { container } = render(<WebTileHeader tileId={TileId.RETENTION} overflowMenuItems={noopMenuItems} />)
        expect(within(container).queryByText('Retention')).toBeNull()
        expect(within(container).queryByText('Sources by')).toBeNull()
    })

    test('renders interval selector label when intervalSelector prop is provided', () => {
        const { container } = render(
            <WebTileHeader
                tileId={TileId.GRAPHS}
                intervalSelector={{ node: <span data-attr="my-interval">node</span> }}
                overflowMenuItems={noopMenuItems}
            />
        )
        expect(within(container).getByText('Interval')).toBeTruthy()
        expect(queryByDataAttr(container, 'my-interval')).toBeTruthy()
    })

    test('renders the open-insight button, links to `to`, and fires `onClick` when clicked', () => {
        const onClick = jest.fn()
        const { container } = render(
            <WebTileHeader
                tileId={TileId.SOURCES}
                openInsight={{ to: '/insights/new?web-source', onClick }}
                overflowMenuItems={noopMenuItems}
            />
        )
        const button = queryByDataAttr(container, 'web-analytics-open-insight-SOURCES')
        expect(button).toBeTruthy()
        expect(button?.getAttribute('href')).toBe('/insights/new?web-source')
        fireEvent.click(button!)
        expect(onClick).toHaveBeenCalledTimes(1)
    })

    test('does not render the open-insight button when openInsight is omitted', () => {
        const { container } = render(<WebTileHeader tileId={TileId.SOURCES} overflowMenuItems={noopMenuItems} />)
        expect(queryByDataAttr(container, 'web-analytics-open-insight-SOURCES')).toBeNull()
    })
})
