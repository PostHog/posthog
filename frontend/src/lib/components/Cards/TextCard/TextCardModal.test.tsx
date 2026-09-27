import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DashboardType } from '~/types'

import { TextCardModal } from './TextCardModal'

jest.mock('lib/components/Cards/TextCard/TextCardModalBodyField', () => ({
    TextCardModalBodyField: (): JSX.Element => <div>Dashboard text editor</div>,
}))

const dashboard = {
    id: 123,
    name: 'Test dashboard',
    description: '',
    pinned: false,
    created_at: '2024-01-01T00:00:00Z',
    created_by: null,
    last_accessed_at: null,
    is_shared: false,
    deleted: false,
    creation_mode: 'default',
    tiles: [],
    filters: {},
    tags: [],
    user_access_level: AccessControlLevel.Editor,
} as DashboardType

describe('TextCardModal', () => {
    afterEach(cleanup)

    it.each([
        { approved: true, expected: true },
        { approved: false, expected: false },
    ])('shows the agent context field: $expected when AI approval is $approved', ({ approved, expected }) => {
        initKeaTests(true, undefined, undefined, {
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: approved,
        })

        render(<TextCardModal isOpen onClose={jest.fn()} dashboard={dashboard} textTileId={null} />)

        if (expected) {
            expect(screen.getByText('Agent context')).toBeInTheDocument()
        } else {
            expect(screen.queryByText('Agent context')).not.toBeInTheDocument()
        }
    })
})
