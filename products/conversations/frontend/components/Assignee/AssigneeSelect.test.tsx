import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions } from 'kea'
import type { ReactElement, ReactNode } from 'react'

import { AssigneeSelect } from './AssigneeSelect'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useActions: jest.fn() }))
jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    LemonDropdown: ({
        children,
        onVisibilityChange,
    }: {
        children: ReactNode
        onVisibilityChange?: (visible: boolean) => void
    }): JSX.Element => (
        <div>
            <button onClick={() => onVisibilityChange?.(true)}>Open assignee dropdown</button>
            {children}
        </div>
    ),
}))
jest.mock('./AssigneeDisplay', () => ({
    AssigneeResolver: ({ children }: { children: (props: { assignee: null }) => ReactElement }): ReactElement =>
        children({ assignee: null }),
}))
jest.mock('./AssigneeDropdown', () => ({
    AssigneeDropdown: (): JSX.Element => <div />,
}))

describe('AssigneeSelect', () => {
    const ensureAssigneeTypesLoaded = jest.fn()

    afterEach(() => {
        cleanup()
        ensureAssigneeTypesLoaded.mockClear()
    })

    function renderAssigneeSelect(loadOnOpen = false): void {
        render(
            <AssigneeSelect assignee={null} onChange={jest.fn()} loadOnOpen={loadOnOpen}>
                {() => <button>Assignee</button>}
            </AssigneeSelect>
        )
    }

    it('loads assignee types when mounted by default', () => {
        ;(useActions as jest.Mock).mockReturnValue({ ensureAssigneeTypesLoaded, setSearch: jest.fn() })

        renderAssigneeSelect()

        expect(ensureAssigneeTypesLoaded).toHaveBeenCalledTimes(1)
    })

    it('loads assignee types when the dropdown opens when configured for lazy loading', () => {
        ;(useActions as jest.Mock).mockReturnValue({ ensureAssigneeTypesLoaded, setSearch: jest.fn() })

        renderAssigneeSelect(true)

        expect(ensureAssigneeTypesLoaded).not.toHaveBeenCalled()
        fireEvent.click(screen.getByText('Open assignee dropdown'))
        expect(ensureAssigneeTypesLoaded).toHaveBeenCalledTimes(1)
    })
})
