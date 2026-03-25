import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { ConnectionSelector } from './ConnectionSelector'
import { sqlEditorLogic } from './sqlEditorLogic'

jest.mock('kea', () => {
    const actual = jest.requireActual('kea')

    return {
        ...actual,
        useActions: jest.fn(),
        useValues: jest.fn(),
    }
})

jest.mock('kea-router', () => ({
    router: {
        actions: {
            push: jest.fn(),
        },
    },
}))

jest.mock('lib/lemon-ui/LemonSelect', () => ({
    LemonSelect: ({
        value,
        onChange,
        options,
    }: {
        value?: string
        onChange: (value: string) => void
        options: Array<{ options: Array<{ value: string; label: string }> }>
    }) => (
        <select data-testid="connection-selector" value={value} onChange={(event) => onChange(event.target.value)}>
            {options.flatMap((group) =>
                group.options.map((option) => (
                    <option key={option.value} value={option.value}>
                        {option.label}
                    </option>
                ))
            )}
        </select>
    ),
}))

jest.mock('scenes/urls', () => ({
    urls: {
        dataWarehouseSourceNew: jest.fn(),
        sources: jest.fn(),
    },
}))

jest.mock('./connectionSelectorLogic', () => ({
    ADD_POSTGRES_DIRECT_CONNECTION: 'add-postgres-direct-connection',
    CONFIGURE_SOURCES: 'configure-sources',
    POSTHOG_WAREHOUSE: 'posthog-warehouse',
    connectionSelectorLogic: jest.fn(() => 'connectionSelectorLogic'),
}))

jest.mock('./sqlEditorLogic', () => ({
    sqlEditorLogic: 'sqlEditorLogic',
}))

describe('ConnectionSelector', () => {
    const setSourceQuery = jest.fn()
    const syncUrlWithQuery = jest.fn()

    beforeEach(() => {
        jest.clearAllMocks()

        ;(useValues as jest.Mock).mockImplementation((logic) => {
            if (logic === sqlEditorLogic) {
                return {
                    selectedConnectionId: 'conn-123',
                    sourceQuery: {
                        kind: 'DataVisualizationNode',
                        source: {
                            kind: 'HogQLQuery',
                            query: 'SELECT 1',
                            connectionId: 'conn-123',
                            sendRawQuery: true,
                        },
                    },
                }
            }

            if (logic === 'connectionSelectorLogic') {
                return {
                    connectionSelectOptions: [
                        {
                            options: [
                                { value: 'posthog-warehouse', label: 'PostHog warehouse' },
                                { value: 'conn-123', label: 'warehouse-a (Postgres)' },
                                { value: 'conn-456', label: 'warehouse-b (Postgres)' },
                            ],
                        },
                    ],
                    connectionSelectorValue: 'conn-123',
                    isDirectQueryEnabled: true,
                }
            }

            return {}
        })

        ;(useActions as jest.Mock).mockImplementation((logic) => {
            if (logic === sqlEditorLogic) {
                return {
                    setSourceQuery,
                    syncUrlWithQuery,
                }
            }

            return {}
        })
    })

    afterEach(() => {
        cleanup()
    })

    it('clears sendRawQuery when selecting a different connection', () => {
        render(<ConnectionSelector />)

        fireEvent.change(screen.getByRole('combobox'), { target: { value: 'conn-456' } })

        expect(setSourceQuery).toHaveBeenCalledWith({
            kind: 'DataVisualizationNode',
            source: {
                kind: 'HogQLQuery',
                query: 'SELECT 1',
                connectionId: 'conn-456',
                sendRawQuery: undefined,
            },
        })
        expect(syncUrlWithQuery).toHaveBeenCalledTimes(1)
    })

    it('clears sendRawQuery when switching back to PostHog warehouse', () => {
        render(<ConnectionSelector />)

        fireEvent.change(screen.getByRole('combobox'), { target: { value: 'posthog-warehouse' } })

        expect(setSourceQuery).toHaveBeenCalledWith({
            kind: 'DataVisualizationNode',
            source: {
                kind: 'HogQLQuery',
                query: 'SELECT 1',
                connectionId: undefined,
                sendRawQuery: undefined,
            },
        })
        expect(syncUrlWithQuery).toHaveBeenCalledTimes(1)
    })
})
