import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { VisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { DataTableVisualization } from './DataVisualization'

type LemonTableMockProps = {
    embedded?: boolean
    allowContentScroll?: boolean
}

let mockLatestLemonTableProps: LemonTableMockProps | null = null
const mockLemonTable = jest.fn((props: LemonTableMockProps): null => {
    mockLatestLemonTableProps = props
    return null
})

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    LemonTable: (props: Record<string, unknown>): null => {
        mockLemonTable(props)
        return null
    },
}))

describe('DataTableVisualization', () => {
    const query: VisualizationNode = {
        kind: NodeKind.DataVisualizationNode,
        source: {
            kind: NodeKind.HogQLQuery,
            query: 'select number from numbers(2)',
        },
        display: ChartDisplayType.ActionsTable,
    }

    const cachedResults: HogQLQueryResponse<number[][]> = {
        results: [[1], [2]],
        columns: ['number'],
        types: [['number', 'Int64']],
    }

    beforeEach(() => {
        initKeaTests()
        mockLatestLemonTableProps = null
        mockLemonTable.mockClear()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([false, true])('opens and closes settings in the correct panel (hosted: %s)', async (hosted) => {
        function Visualization(): JSX.Element {
            const [container, setContainer] = useState<HTMLDivElement | null>(null)
            const [isOpen, setIsOpen] = useState(false)
            return (
                <>
                    <div ref={setContainer} data-attr="host-settings" />
                    <DataTableVisualization
                        uniqueKey={`settings-${hosted}`}
                        query={query}
                        setQuery={jest.fn()}
                        cachedResults={cachedResults}
                        editMode
                        context={
                            hosted
                                ? {
                                      visualizationSettingsPanel: {
                                          container,
                                          isOpen,
                                          onToggle: () => setIsOpen(!isOpen),
                                      },
                                  }
                                : undefined
                        }
                    />
                </>
            )
        }
        const { container } = render(<Visualization />)
        expect(screen.queryByText('Conditional formatting')).toBeNull()
        await userEvent.click(screen.getByLabelText('Visualization settings'))
        const settings = await screen.findByText('Conditional formatting')
        const host = screen.getByTestId('host-settings')
        expect(host.contains(settings)).toBe(hosted)
        expect(container.querySelector('.DataVisualization')!.contains(settings)).toBe(!hosted)
        await userEvent.click(settings)
        expect(within(hosted ? host : container).getByText('Add rule')).toBeTruthy()
        await userEvent.click(screen.getByLabelText('Visualization settings'))
        expect(screen.queryByText('Conditional formatting')).toBeNull()
    })

    test.each([
        { embedded: true, expectedAllowContentScroll: true },
        { embedded: false, expectedAllowContentScroll: false },
    ])(
        'sets table scroll mode to $expectedAllowContentScroll when embedded is $embedded',
        async ({ embedded, expectedAllowContentScroll }) => {
            render(
                <DataTableVisualization
                    uniqueKey={`data-visualization-scroll-${embedded}`}
                    query={query}
                    setQuery={jest.fn()}
                    cachedResults={cachedResults}
                    readOnly
                    embedded={embedded}
                />
            )

            await waitFor(() => {
                if (!mockLatestLemonTableProps) {
                    throw new Error('Expected LemonTable to render')
                }
            })

            if (!mockLatestLemonTableProps) {
                throw new Error('Expected LemonTable props to be recorded')
            }
            expect(mockLatestLemonTableProps.embedded).toBe(embedded)
            expect(mockLatestLemonTableProps.allowContentScroll).toBe(expectedAllowContentScroll)
        }
    )
})
