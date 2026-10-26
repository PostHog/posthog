import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { biDrilldownLogic } from './biDrilldownLogic'
import { BIDrilldownMenu } from './BIDrilldownMenu'
import { buildBIQuery, DEFAULT_BI_CONFIG } from './biEditorTypes'

describe('native result-menu links', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it.each([false, true])(
        'renders real destinations without intercepting modified clicks (quill=%s)',
        async (quill) => {
            featureFlagLogic.actions.setFeatureFlags([], { 'today-rail-nav': quill })
            const config = {
                ...DEFAULT_BI_CONFIG,
                source: { table: 'orders' },
                rows: [
                    {
                        id: 'status',
                        name: 'Status',
                        expression: 'status',
                        type: 'string' as const,
                        source: { table: 'orders' },
                    },
                ],
            }
            const query: BIVisualizationNode = {
                ...buildBIQuery(config)!.node,
                kind: NodeKind.BIVisualizationNode,
                config,
            }
            const props = {
                key: 'native-links',
                query,
                dashboardMenu: true,
            }
            const logic = biDrilldownLogic(props)
            const unmount = logic.mount()
            try {
                logic.actions.inspect({ status: 'paid' })
                render(<BIDrilldownMenu logicProps={props} />)
                await screen.findByText('View underlying rows')
                const names = ['View underlying rows', 'Open in SQL editor']
                for (const name of names) {
                    const link = screen.getByText(name).closest('a')!
                    expect(link).not.toBeNull()
                    expect(link.getAttribute('href')).toMatch(/\/project\/\d+\/(dashboard|bi|sql)/)
                    for (const modifier of [{ metaKey: true }, { ctrlKey: true }]) {
                        const click = new MouseEvent('click', { bubbles: true, cancelable: true, ...modifier })
                        act(() => {
                            link.dispatchEvent(click)
                        })
                        expect(click.defaultPrevented).toBe(false)
                        expect(logic.values.record).toEqual({ status: 'paid' })
                    }
                }
                expect(screen.getAllByRole('menuitem').map((item) => item.textContent)).toEqual(names)
                expect(screen.queryByText('Filter dashboard by this result')).not.toBeInTheDocument()
                expect(screen.queryByText('Filter in new worksheet')).not.toBeInTheDocument()
                fireEvent.click(screen.getByText('View underlying rows'))
                expect(logic.values.showRows).toBe(true)
                act(() => logic.actions.inspect({ count: 8 }))
                expect(screen.queryByText('Filter dashboard by this result')).not.toBeInTheDocument()
                expect(screen.getAllByRole('menuitem')).toHaveLength(2)
                fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' })
                expect(logic.values.record).toBeNull()
            } finally {
                unmount()
            }
        }
    )
})
