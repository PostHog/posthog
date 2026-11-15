import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

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

    it('keeps agent context collapsed until the user opens it', async () => {
        initKeaTests(true, undefined, undefined, {
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: true,
        })

        render(<TextCardModal isOpen onClose={jest.fn()} dashboard={dashboard} textTileId={null} />)

        expect(screen.getByText('Agent context')).toBeInTheDocument()
        expect(screen.queryByLabelText('Agent context')).not.toBeInTheDocument()

        await userEvent.click(screen.getByText('Agent context'))

        expect(screen.getByLabelText('Agent context')).toBeInTheDocument()
    })

    it('hides agent context without AI data processing approval', () => {
        initKeaTests(true, undefined, undefined, {
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: false,
        })

        render(<TextCardModal isOpen onClose={jest.fn()} dashboard={dashboard} textTileId={null} />)

        expect(screen.queryByText('Agent context')).not.toBeInTheDocument()
    })
})
