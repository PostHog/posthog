import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { NotebookNodeType } from '../../types'
import { notebookNodeLogic } from '../notebookNodeLogic'
import { getCellLabel, NotebookNodeTitle } from './NotebookNodeTitle'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
}))

jest.mock('scenes/notebooks/Notebook/notebookLogic', () => ({
    notebookLogic: { __mock: 'notebookLogic' },
}))

jest.mock('../notebookNodeLogic', () => ({
    notebookNodeLogic: { __mock: 'notebookNodeLogic' },
}))

jest.mock('~/queries/utils', () => ({
    isHogQLQuery: jest.fn((query: unknown) => (query as { kind?: string } | undefined)?.kind === 'HogQLQuery'),
}))

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    Tooltip: ({ children, title }: { children: React.ReactNode; title: string }) => (
        <div data-attr={title}>{children}</div>
    ),
    LemonInput: ({
        value,
        onChange,
        onBlur,
        onKeyUp,
        onFocus,
        placeholder,
    }: {
        value: string
        onChange: (v: string) => void
        onBlur: () => void
        onKeyUp: (e: React.KeyboardEvent<HTMLInputElement>) => void
        onFocus: (e: React.FocusEvent<HTMLInputElement>) => void
        placeholder: string
    }) => (
        <input
            value={value}
            onChange={(e) => onChange?.(e.target.value)}
            onBlur={onBlur}
            onKeyUp={onKeyUp}
            onFocus={onFocus}
            placeholder={placeholder}
            data-attr="title-input"
        />
    ),
    LemonTag: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}))

const mockedUseValues = useValues as jest.Mock
const mockedUseActions = useActions as jest.Mock

function isNotebookLogicRef(logic: unknown): boolean {
    return logic === notebookLogic || (logic as { __mock?: string })?.__mock === 'notebookLogic'
}

function isNotebookNodeLogicRef(logic: unknown): boolean {
    return logic === notebookNodeLogic || (logic as { __mock?: string })?.__mock === 'notebookNodeLogic'
}

const defaultNotebookLogicValues = {
    isEditable: true,
    sqlNodeIndices: new Map<string, number>(),
}

const mockUpdateAttributes = jest.fn()
const mockToggleEditingTitle = jest.fn()

function setupMocks(nodeLogicValues: Record<string, unknown>, notebookValues: Record<string, unknown> = {}): void {
    mockedUseValues.mockImplementation((logic: unknown) => {
        if (isNotebookLogicRef(logic)) {
            return { ...defaultNotebookLogicValues, ...notebookValues }
        }
        if (isNotebookNodeLogicRef(logic)) {
            return nodeLogicValues
        }
        throw new Error(`Unhandled useValues for: ${JSON.stringify(logic)}`)
    })

    mockedUseActions.mockImplementation((logic: unknown) => {
        if (isNotebookNodeLogicRef(logic)) {
            return {
                updateAttributes: mockUpdateAttributes,
                toggleEditingTitle: mockToggleEditingTitle,
            }
        }
        return {}
    })
}

describe('getCellLabel', () => {
    test.each([
        { nodeIndex: undefined, expected: null },
        { nodeIndex: 0, expected: null },
        { nodeIndex: 5, expected: 'SQL 5' },
    ])('returns $expected for index=$nodeIndex', ({ nodeIndex, expected }) => {
        expect(getCellLabel(nodeIndex)).toBe(expected)
    })
})

describe('NotebookNodeTitle', () => {
    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
    })

    describe('rendering', () => {
        test.each([
            {
                scenario: 'non-indexed cell displays resolved title',
                nodeValues: {
                    nodeAttributes: { nodeId: 'abc', title: undefined },
                    title: 'My Insight',
                    titlePlaceholder: 'My Insight',
                    isEditingTitle: false,
                    nodeType: NotebookNodeType.Recording,
                },
                expectedText: 'My Insight',
            },
            {
                scenario: 'indexed cell without custom title displays cell label',
                nodeValues: {
                    nodeAttributes: { nodeId: 'sql1', title: undefined, query: { kind: 'HogQLQuery' } },
                    title: 'SQL',
                    titlePlaceholder: 'SQL',
                    isEditingTitle: false,
                    nodeType: NotebookNodeType.Query,
                },
                notebookValues: {
                    sqlNodeIndices: new Map([['sql1', 1]]),
                },
                expectedText: 'SQL 1',
            },
            {
                scenario: 'indexed cell with custom title displays both',
                nodeValues: {
                    nodeAttributes: { nodeId: 'sql1', title: 'Data cleanup', query: { kind: 'HogQLQuery' } },
                    title: 'SQL',
                    titlePlaceholder: 'SQL',
                    isEditingTitle: false,
                    nodeType: NotebookNodeType.Query,
                },
                notebookValues: {
                    sqlNodeIndices: new Map([['sql1', 1]]),
                },
                expectedText: 'SQL 1',
                alsoExpected: 'Data cleanup',
            },
        ])(
            '$scenario',
            ({
                nodeValues,
                notebookValues,
                expectedText,
                alsoExpected,
            }: {
                scenario: string
                nodeValues: Record<string, unknown>
                notebookValues?: Record<string, unknown>
                expectedText: string
                alsoExpected?: string
            }) => {
                setupMocks(nodeValues, notebookValues)
                render(<NotebookNodeTitle />)

                expect(screen.getByText(expectedText)).toBeInTheDocument()
                if (alsoExpected) {
                    expect(screen.getByText(alsoExpected)).toBeInTheDocument()
                }
            }
        )
    })

    describe('pre-fill behavior', () => {
        test.each([
            {
                scenario: 'non-indexed cell without custom title pre-fills with resolved title',
                nodeValues: {
                    nodeAttributes: { nodeId: 'abc', title: undefined },
                    title: 'My Insight',
                    titlePlaceholder: 'My Insight',
                    isEditingTitle: true,
                    nodeType: NotebookNodeType.Recording,
                },
                expectedValue: 'My Insight',
            },
            {
                scenario: 'non-indexed cell with custom title pre-fills with custom title',
                nodeValues: {
                    nodeAttributes: { nodeId: 'abc', title: 'Custom Name' },
                    title: 'Custom Name',
                    titlePlaceholder: 'Original',
                    isEditingTitle: true,
                    nodeType: NotebookNodeType.Recording,
                },
                expectedValue: 'Custom Name',
            },
            {
                scenario: 'indexed cell without custom title pre-fills empty',
                nodeValues: {
                    nodeAttributes: { nodeId: 'sql1', title: undefined, query: { kind: 'HogQLQuery' } },
                    title: 'SQL',
                    titlePlaceholder: 'SQL',
                    isEditingTitle: true,
                    nodeType: NotebookNodeType.Query,
                },
                notebookValues: {
                    sqlNodeIndices: new Map([['sql1', 1]]),
                },
                expectedValue: '',
            },
            {
                scenario: 'indexed cell with custom title pre-fills with custom title',
                nodeValues: {
                    nodeAttributes: { nodeId: 'sql1', title: 'My Script', query: { kind: 'HogQLQuery' } },
                    title: 'SQL',
                    titlePlaceholder: 'SQL',
                    isEditingTitle: true,
                    nodeType: NotebookNodeType.Query,
                },
                notebookValues: {
                    sqlNodeIndices: new Map([['sql1', 1]]),
                },
                expectedValue: 'My Script',
            },
        ])(
            '$scenario',
            ({
                nodeValues,
                notebookValues,
                expectedValue,
            }: {
                scenario: string
                nodeValues: Record<string, unknown>
                notebookValues?: Record<string, unknown>
                expectedValue: string
            }) => {
                setupMocks(nodeValues, notebookValues)
                render(<NotebookNodeTitle />)

                const input = screen.getByTestId('title-input') as HTMLInputElement
                expect(input.value).toBe(expectedValue)
            }
        )
    })

    describe('commit guard', () => {
        test.each([
            {
                scenario: 'indexed cell blur without editing does not save',
                nodeValues: {
                    nodeAttributes: { nodeId: 'sql1', title: undefined, query: { kind: 'HogQLQuery' } },
                    title: 'SQL',
                    titlePlaceholder: 'SQL',
                    isEditingTitle: true,
                    nodeType: NotebookNodeType.Query,
                },
                notebookValues: {
                    sqlNodeIndices: new Map([['sql1', 1]]),
                },
            },
            {
                scenario: 'non-indexed cell blur without editing does not save',
                nodeValues: {
                    nodeAttributes: { nodeId: 'abc', title: undefined },
                    title: 'My Insight',
                    titlePlaceholder: 'My Insight',
                    isEditingTitle: true,
                    nodeType: NotebookNodeType.Recording,
                },
            },
        ])(
            '$scenario',
            ({
                nodeValues,
                notebookValues,
            }: {
                scenario: string
                nodeValues: Record<string, unknown>
                notebookValues?: Record<string, unknown>
            }) => {
                setupMocks(nodeValues, notebookValues)
                render(<NotebookNodeTitle />)

                const input = screen.getByTestId('title-input')
                fireEvent.blur(input)

                expect(mockUpdateAttributes).not.toHaveBeenCalled()
                expect(mockToggleEditingTitle).toHaveBeenCalledWith(false)
            }
        )
    })

    describe('edit interactions', () => {
        it('saves on blur after changing the value', () => {
            setupMocks({
                nodeAttributes: { nodeId: 'abc', title: undefined },
                title: 'My Insight',
                titlePlaceholder: 'My Insight',
                isEditingTitle: true,
                nodeType: NotebookNodeType.Recording,
            })
            render(<NotebookNodeTitle />)

            const input = screen.getByTestId('title-input')
            fireEvent.change(input, { target: { value: 'Renamed' } })
            fireEvent.blur(input)

            expect(mockUpdateAttributes).toHaveBeenCalledWith({ title: 'Renamed' })
            expect(mockToggleEditingTitle).toHaveBeenCalledWith(false)
        })

        it('saves on Enter after changing the value', () => {
            setupMocks({
                nodeAttributes: { nodeId: 'abc', title: undefined },
                title: 'My Insight',
                titlePlaceholder: 'My Insight',
                isEditingTitle: true,
                nodeType: NotebookNodeType.Recording,
            })
            render(<NotebookNodeTitle />)

            const input = screen.getByTestId('title-input')
            fireEvent.change(input, { target: { value: 'New Title' } })
            fireEvent.keyUp(input, { key: 'Enter' })

            expect(mockUpdateAttributes).toHaveBeenCalledWith({ title: 'New Title' })
        })

        it('cancels on Escape without saving', () => {
            setupMocks({
                nodeAttributes: { nodeId: 'abc', title: undefined },
                title: 'My Insight',
                titlePlaceholder: 'My Insight',
                isEditingTitle: true,
                nodeType: NotebookNodeType.Recording,
            })
            render(<NotebookNodeTitle />)

            const input = screen.getByTestId('title-input')
            fireEvent.change(input, { target: { value: 'Some edit' } })
            fireEvent.keyUp(input, { key: 'Escape' })

            expect(mockUpdateAttributes).not.toHaveBeenCalled()
            expect(mockToggleEditingTitle).toHaveBeenCalledWith(false)
        })

        it('clearing the title saves undefined', () => {
            setupMocks(
                {
                    nodeAttributes: { nodeId: 'sql1', title: 'My Script', query: { kind: 'HogQLQuery' } },
                    title: 'SQL',
                    titlePlaceholder: 'SQL',
                    isEditingTitle: true,
                    nodeType: NotebookNodeType.Query,
                },
                {
                    sqlNodeIndices: new Map([['sql1', 1]]),
                }
            )
            render(<NotebookNodeTitle />)

            const input = screen.getByTestId('title-input')
            fireEvent.change(input, { target: { value: '' } })
            fireEvent.blur(input)

            expect(mockUpdateAttributes).toHaveBeenCalledWith({ title: undefined })
        })
    })
})
