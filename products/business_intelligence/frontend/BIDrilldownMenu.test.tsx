import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { biDrilldownLogic } from './biDrilldownLogic'
import { BIDrilldownMenu } from './BIDrilldownMenu'
import { BIDrilldownModal } from './BIDrilldownModal'
import { buildBIQuery, DEFAULT_BI_CONFIG } from './biEditorTypes'

describe('native result-menu links', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it.each([
        [false, false],
        [true, false],
        [false, true],
        [true, true],
    ])(
        'renders real destinations without intercepting modified clicks (quill=%s, filtering=%s)',
        async (quill, filtering) => {
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
            const onFilterDashboard = jest.fn()
            const props = {
                key: 'native-links',
                query,
                onFilterDashboard: filtering ? onFilterDashboard : undefined,
                getDashboardFilterUrl: () => '/project/1/dashboard/1#bi_filter=selection',
                isDashboardFilterSelected: (record: Record<string, unknown>) => record.status === 'paid',
            }
            const logic = biDrilldownLogic(props)
            const unmount = logic.mount()
            try {
                logic.actions.setInteraction({ x: 40, y: 40 })
                logic.actions.inspect({ status: 'paid' })
                render(<BIDrilldownMenu logicProps={props} />)
                await screen.findByText('View underlying rows')
                const names = ['View underlying rows', 'Open in SQL editor', ...(filtering ? ['Remove filter'] : [])]
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
                if (filtering) {
                    expect(onFilterDashboard).not.toHaveBeenCalled()
                    fireEvent.click(screen.getByText('Remove filter'))
                    expect(onFilterDashboard).toHaveBeenCalledWith({ status: 'paid' })
                    expect(logic.values.record).toBeNull()
                    act(() => {
                        logic.actions.setInteraction({ x: 40, y: 40 })
                        logic.actions.inspect({ status: 'refunded' })
                    })
                    expect(screen.getByText('Filter dashboard by this result')).toBeInTheDocument()
                }
                fireEvent.click(screen.getByText('View underlying rows'))
                expect(logic.values.showRows).toBe(true)
                act(() => logic.actions.inspect({ count: 8 }))
                expect(screen.getAllByRole('menuitem')).toHaveLength(filtering ? 3 : 2)
                if (filtering) {
                    act(() => logic.actions.filterDashboard())
                    expect(onFilterDashboard).toHaveBeenCalledTimes(1)
                    expect(logic.values.record).toEqual({ count: 8 })
                }
                fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' })
                expect(logic.values.record).toBeNull()
                act(() => {
                    logic.actions.close()
                    logic.actions.inspect({ status: 'refunded' })
                })
                render(<BIDrilldownModal logicProps={props} />)
                await screen.findByText('Explore this result')
                if (filtering) {
                    const link = screen.getByText('Filter dashboard by this result').closest('a')!
                    expect(link).toHaveAttribute('href', '/project/1/dashboard/1#bi_filter=selection')
                    const callsBeforeModifiedClicks = onFilterDashboard.mock.calls.length
                    for (const modifier of [
                        { metaKey: true },
                        { ctrlKey: true },
                        { shiftKey: true },
                        { altKey: true },
                    ]) {
                        const modified = new MouseEvent('click', { bubbles: true, cancelable: true, ...modifier })
                        act(() => {
                            link.dispatchEvent(modified)
                        })
                        expect(modified.defaultPrevented).toBe(false)
                        expect(logic.values.record).toEqual({ status: 'refunded' })
                        expect(onFilterDashboard).toHaveBeenCalledTimes(callsBeforeModifiedClicks)
                    }
                    fireEvent.click(link)
                    expect(onFilterDashboard).toHaveBeenLastCalledWith({ status: 'refunded' })
                    expect(logic.values.record).toBeNull()
                    act(() => logic.actions.inspect({ status: 'paid' }))
                    expect(screen.getByText('Remove filter')).toBeInTheDocument()
                    act(() => logic.actions.inspect({ count: 8 }))
                    const disabledFilter = screen.getByText('Filter dashboard by this result').closest('button')!
                    expect(disabledFilter).toHaveAttribute('aria-disabled', 'true')
                    const calls = onFilterDashboard.mock.calls.length
                    fireEvent.click(disabledFilter)
                    expect(onFilterDashboard).toHaveBeenCalledTimes(calls)
                } else {
                    expect(screen.queryByText('Filter dashboard by this result')).not.toBeInTheDocument()
                }
            } finally {
                unmount()
            }
        }
    )
})
