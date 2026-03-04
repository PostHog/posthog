import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { DashboardsTable } from './DashboardsTable'

jest.mock('kea', () => {
    const actualKea = jest.requireActual('kea')
    return {
        ...actualKea,
        useActions: () => ({}),
        useValues: (logic: any) => {
            // For this focused test we only care about projectTreeDataLogic.itemsByRef
            if (logic && logic.path?.includes?.('projectTreeDataLogic')) {
                return {
                    itemsByRef: {
                        'dashboard::1': { path: 'Unfiled/Foo' },
                        'dashboard::2': { path: 'Foo/Bar/Baz' },
                    },
                }
            }
            return {}
        },
    }
})

describe('DashboardsTable folder column', () => {
    it('renders folder names based on project tree paths', () => {
        render(
            <Provider>
                <DashboardsTable
                    dashboards={[
                        { id: 1, name: 'A', tags: [], created_by: null } as any,
                        { id: 2, name: 'B', tags: [], created_by: null } as any,
                        { id: 3, name: 'C', tags: [], created_by: null } as any,
                    ]}
                    dashboardsLoading={false}
                />
            </Provider>
        )

        // Dashboard 1: Unfiled/Foo -> "Unfiled"
        expect(screen.getByText('Unfiled')).toBeInTheDocument()

        // Dashboard 2: Foo/Bar/Baz -> "Foo / Bar"
        expect(screen.getByText('Foo / Bar')).toBeInTheDocument()

        // Dashboard 3: no entry -> "—"
        expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(1)
    })
})
