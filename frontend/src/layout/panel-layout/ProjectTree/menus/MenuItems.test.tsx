import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useActions, useValues } from 'kea'

import { MenuItems } from './MenuItems'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
}))

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: jest.fn(() => true),
}))

jest.mock('scenes/settings/environment/groupAnalyticsConfigLogic', () => ({
    groupAnalyticsConfigLogic: { __mock: 'groupAnalyticsConfigLogic' },
}))

jest.mock('../../PinnedFolder/editCustomProductsModalLogic', () => ({
    editCustomProductsModalLogic: { __mock: 'editCustomProductsModalLogic' },
}))

jest.mock('../../panelLayoutLogic', () => ({
    panelLayoutLogic: { __mock: 'panelLayoutLogic' },
}))

jest.mock('../projectTreeDataLogic', () => ({
    projectTreeDataLogic: { __mock: 'projectTreeDataLogic' },
}))

jest.mock('../projectTreeLogic', () => ({
    projectTreeLogic: jest.fn(() => ({ __mock: 'projectTreeLogic' })),
}))

jest.mock('lib/components/FileSystem/MoveTo/moveToLogic', () => ({
    moveToLogic: { __mock: 'moveToLogic' },
}))

jest.mock('lib/components/FileSystem/LinkTo/linkToLogic', () => ({
    linkToLogic: { __mock: 'linkToLogic' },
}))

const mockedUseValues = useValues as jest.Mock
const mockedUseActions = useActions as jest.Mock

const mockMoveShortcutInStarred = jest.fn()

const shortcutItem = {
    id: 'shortcuts/shortcut-2',
    name: 'Saved insight',
    displayName: <>Saved insight</>,
    record: {
        id: 'shortcut-2',
        path: 'Saved insight',
        type: 'insight',
        protocol: 'shortcuts://',
        href: '/insights/1',
    },
}

function setupMocks(canMoveUp: boolean, canMoveDown: boolean): void {
    mockedUseValues.mockImplementation((logic: unknown) => {
        if ((logic as { __mock?: string } | null | undefined)?.__mock === 'projectTreeDataLogic') {
            return {
                shortcutNonFolderPaths: new Set<string>(),
                shortcutEntryIdMap: new Map([['shortcuts/shortcut-2', 'shortcut-2']]),
                shortcutMoveAvailability: new Map([['shortcut-2', { canMoveUp, canMoveDown }]]),
            }
        }

        if ((logic as { __mock?: string } | null | undefined)?.__mock === 'groupAnalyticsConfigLogic') {
            return { groupTypes: [] }
        }

        if ((logic as { __mock?: string } | null | undefined)?.__mock === 'editCustomProductsModalLogic') {
            return { selectedPaths: new Set<string>() }
        }

        if ((logic as { __mock?: string } | null | undefined)?.__mock === 'projectTreeLogic') {
            return {
                checkedItems: {},
                checkedItemCountNumeric: 0,
                checkedItemsArray: [],
            }
        }

        return {}
    })

    mockedUseActions.mockImplementation((logic: unknown) => {
        if ((logic as { __mock?: string } | null | undefined)?.__mock === 'projectTreeDataLogic') {
            return {
                deleteShortcut: jest.fn(),
                addShortcutItem: jest.fn(),
                moveShortcutInStarred: mockMoveShortcutInStarred,
            }
        }

        if ((logic as { __mock?: string } | null | undefined)?.__mock === 'projectTreeLogic') {
            return {
                createFolder: jest.fn(),
                deleteItem: jest.fn(),
                deleteCheckedItems: jest.fn(),
                onItemChecked: jest.fn(),
                moveCheckedItems: jest.fn(),
                linkCheckedItems: jest.fn(),
                assureVisibility: jest.fn(),
                setEditingItemId: jest.fn(),
            }
        }

        if ((logic as { __mock?: string } | null | undefined)?.__mock === 'moveToLogic') {
            return { openMoveToModal: jest.fn() }
        }

        if ((logic as { __mock?: string } | null | undefined)?.__mock === 'linkToLogic') {
            return { openLinkToModal: jest.fn() }
        }

        if ((logic as { __mock?: string } | null | undefined)?.__mock === 'editCustomProductsModalLogic') {
            return { toggleProduct: jest.fn() }
        }

        if ((logic as { __mock?: string } | null | undefined)?.__mock === 'panelLayoutLogic') {
            return { resetPanelLayout: jest.fn() }
        }

        if ((logic as { __mock?: string } | null | undefined)?.__mock === 'groupAnalyticsConfigLogic') {
            return { deleteGroupType: jest.fn() }
        }

        return {}
    })
}

describe('MenuItems', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('shows move actions for starred items and dispatches the matching reorder action', async () => {
        setupMocks(true, true)

        render(<MenuItems item={shortcutItem} type="dropdown" root="shortcuts://" />)

        expect(screen.getByText('Move up')).toBeInTheDocument()
        expect(screen.getByText('Move down')).toBeInTheDocument()

        await userEvent.click(screen.getByText('Move up'))
        expect(mockMoveShortcutInStarred).toHaveBeenCalledWith('shortcut-2', 'up')

        await userEvent.click(screen.getByText('Move down'))
        expect(mockMoveShortcutInStarred).toHaveBeenCalledWith('shortcut-2', 'down')
    })

    it('disables move actions when the starred item is already at the boundary', () => {
        setupMocks(false, true)

        render(<MenuItems item={shortcutItem} type="dropdown" root="shortcuts://" />)

        expect(screen.getByText('Move up').closest('button')).toBeDisabled()
        expect(screen.getByText('Move down').closest('button')).not.toBeDisabled()
    })
})
