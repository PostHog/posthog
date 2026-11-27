import { cleanup, render } from '@testing-library/react'
import { createRef } from 'react'

import { EntityDrawer } from './EntityDrawer'

describe('EntityDrawer', () => {
    afterEach(cleanup)

    it('renders loaded tiles, skeletons for loading ones, and only the sections that have content', () => {
        const { container, getByText, queryByText } = render(
            <EntityDrawer
                aria-label="Tool detail"
                data-attr="tool-drawer"
                rect={{ top: 0, right: 1200, height: 600, width: 1200 }}
                width={480}
                resizer={null}
                containerRef={createRef<HTMLElement>()}
                onClose={jest.fn()}
                title="search_knowledge_base"
                tiles={[
                    { label: 'Calls', value: '9,410' },
                    { label: 'First seen', value: 'Nov 12, 2026', loading: true },
                ]}
                sections={[
                    { title: 'Recent traces', content: <span>Three rows</span> },
                    { title: 'Recent failures', content: null },
                ]}
            />
        )

        expect(getByText('9,410')).toBeTruthy()
        expect(queryByText('Nov 12, 2026')).toBeNull()
        expect(container.querySelectorAll('.LemonSkeleton')).toHaveLength(1)
        expect(getByText('Recent traces')).toBeTruthy()
        expect(queryByText('Recent failures')).toBeNull()
        expect(container.querySelector('[data-attr="tool-drawer-close"]')).not.toBeNull()
    })
})
