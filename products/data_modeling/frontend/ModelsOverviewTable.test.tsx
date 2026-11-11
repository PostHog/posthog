import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import { ModelsOverviewTable } from './ModelsOverviewTable'

const DATA = Array.from({ length: 12 }, (_, index) => ({ id: index, name: `Model ${index}` }))
const COLUMNS = [{ title: 'Name', dataIndex: 'name' as const }]

describe('ModelsOverviewTable', () => {
    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('keeps the settled height while loading refreshes a short page', () => {
        let measuredHeight = 500
        jest.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
            () => ({ height: measuredHeight }) as DOMRect
        )
        jest.spyOn(globalThis, 'ResizeObserver').mockImplementation(
            () => ({ observe: () => null, unobserve: () => null, disconnect: () => null }) as ResizeObserver
        )

        const table = (loading: boolean): JSX.Element => (
            <ModelsOverviewTable
                columns={COLUMNS}
                dataSource={DATA}
                loading={loading}
                rowKey="id"
                data-attr="models-overview-test"
            />
        )
        const { container, rerender } = render(table(false))
        const wrapper = container.querySelector<HTMLElement>('[data-attr="models-overview-test"]')!

        expect(wrapper).toHaveStyle({ minHeight: '500px' })

        measuredHeight = 100
        rerender(table(true))
        expect(wrapper).toHaveStyle({ minHeight: '500px' })

        rerender(table(false))
        expect(wrapper).toHaveStyle({ minHeight: '500px' })
    })
})
