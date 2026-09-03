import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useActions, useMountedLogic, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'

import { AccountNotebooksExpansion } from './AccountNotebooksExpansion'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useActions: jest.fn(),
    useMountedLogic: jest.fn(),
    useValues: jest.fn(),
}))

jest.mock('lib/logic/featureFlagLogic', () => ({ featureFlagLogic: { kind: 'featureFlags' } }))
jest.mock('lib/utils/accessControlUtils', () => ({ userHasAccess: jest.fn(() => true) }))
jest.mock('scenes/notebooks/NotebookPanel/notebookPanelLogic', () => ({
    notebookPanelLogic: { kind: 'notebookPanel' },
}))
jest.mock('../EventStream/AccountEventStreamToggle', () => ({ AccountEventStreamToggle: () => null }))
jest.mock('../CustomerTasks/CustomerTasksTabContent', () => ({ CustomerTasksTabContent: () => null }))
jest.mock('../CustomerTasks/customerTasksLogic', () => ({ customerTasksLogic: () => ({ kind: 'tasks' }) }))
jest.mock('./AccountBillingExpansion', () => ({ AccountBillingExpansion: () => null }))
jest.mock('./AccountConversationsExpansion', () => ({ AccountConversationsExpansion: () => null }))
jest.mock('./AccountFeatureRequestsExpansion', () => ({ AccountFeatureRequestsExpansion: () => null }))
jest.mock('./AccountMeetingsExpansion', () => ({ AccountMeetingsExpansion: () => null }))
jest.mock('./AccountOpportunitiesExpansion', () => ({ AccountOpportunitiesExpansion: () => null }))
jest.mock('./AccountRelatedUsersExpansion', () => ({ AccountRelatedUsersExpansion: () => null }))
jest.mock('./AccountRelationshipsExpansion', () => ({ AccountRelationshipsExpansion: () => null }))
jest.mock('./accountBillingLogic', () => ({ accountBillingLogic: () => ({ kind: 'billing' }) }))
jest.mock('./accountConversationsLogic', () => ({ accountConversationsLogic: () => ({ kind: 'conversations' }) }))
jest.mock('./accountEmailThreadsLogic', () => ({ accountEmailThreadsLogic: () => ({ kind: 'emailThreads' }) }))
jest.mock('./accountLinksLogic', () => ({ accountLinksLogic: () => ({ kind: 'links' }) }))
jest.mock('./accountMeetingsLogic', () => ({ accountMeetingsLogic: () => ({ kind: 'meetings' }) }))
jest.mock('./accountNotebooksLogic', () => ({ accountNotebooksLogic: () => ({ kind: 'notebooks' }) }))
jest.mock('./accountOpportunitiesLogic', () => ({ accountOpportunitiesLogic: () => ({ kind: 'opportunities' }) }))
jest.mock('./accountRelatedUsersLogic', () => ({ accountRelatedUsersLogic: () => ({ kind: 'users' }) }))
jest.mock('./accountRelationshipsLogic', () => ({ accountRelationshipsLogic: () => ({ kind: 'relationships' }) }))
jest.mock('./accountSummariesLogic', () => ({ accountSummariesLogic: () => ({ kind: 'summaries' }) }))
jest.mock('./accountsExpansionLogic', () => ({ accountsExpansionLogic: { kind: 'expansion' } }))
jest.mock('./constants', () => ({ AccountsEvents: { LinkClicked: 'link clicked', NoteClicked: 'note clicked' } }))
jest.mock('./EditAccountLinksButton', () => ({ EditAccountLinksButton: () => null }))

describe('AccountNotebooksExpansion', () => {
    let customerTasksEnabled = false

    beforeEach(() => {
        ;(useMountedLogic as jest.Mock).mockImplementation(() => undefined)
        ;(useActions as jest.Mock).mockImplementation(() => ({
            createNote: jest.fn(),
            selectNotebook: jest.fn(),
            setActiveTab: jest.fn(),
            setSearchTerm: jest.fn(),
            setSorting: jest.fn(),
        }))
        ;(useValues as jest.Mock).mockImplementation((logic: { kind?: string }) => {
            switch (logic.kind) {
                case 'featureFlags':
                    return { featureFlags: { [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS]: customerTasksEnabled } }
                case 'expansion':
                    return { activeTabFor: () => 'notes' }
                case 'links':
                    return { accountLoading: false, links: [] }
                case 'relationships':
                    return { activeRelationships: [] }
                case 'notebooks':
                    return {
                        createdNoteLoading: false,
                        notebooks: [],
                        notebooksResponseLoading: false,
                        pagination: undefined,
                        searchTerm: '',
                        sorting: undefined,
                    }
                default:
                    return {}
            }
        })
    })

    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
    })

    test.each([
        [true, true],
        [false, false],
    ])('shows the Tasks tab only when the customer tasks flag is %s', (enabled, visible) => {
        customerTasksEnabled = enabled
        render(<AccountNotebooksExpansion accountId="account-1" externalId="external-1" />)

        if (visible) {
            expect(screen.getByText('Tasks')).toBeInTheDocument()
        } else {
            expect(screen.queryByText('Tasks')).not.toBeInTheDocument()
        }
        // Mounting the tasks logic loads tasks, so an expanded row must not mount it without the tab.
        const mountedTasksLogic = (useMountedLogic as jest.Mock).mock.calls.some(
            ([logic]: [{ kind?: string }]) => logic?.kind === 'tasks'
        )
        expect(mountedTasksLogic).toBe(visible)
    })
})
