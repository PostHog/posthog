import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'
import { type ReactNode } from 'react'

import { KnowledgeSource } from './businessKnowledgeLogic'
import { BusinessKnowledgeScene } from './BusinessKnowledgeScene'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
}))

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: (): boolean => true,
}))

jest.mock('~/layout/scenes/components/SceneContent', () => ({
    SceneContent: ({ children }: { children: ReactNode }): JSX.Element => <>{children}</>,
}))

jest.mock('~/layout/scenes/components/SceneTitleSection', () => ({
    SceneTitleSection: (): null => null,
}))

jest.mock('../components/BusinessKnowledgeTabs', () => ({
    BusinessKnowledgeTabs: (): null => null,
}))

jest.mock('../components/CreateKnowledgeSourceModal', () => ({
    CreateKnowledgeSourceModal: (): null => null,
}))

jest.mock('../components/EditKnowledgeSourceModal', () => ({
    EditKnowledgeSourceModal: (): null => null,
}))

jest.mock('./businessKnowledgeLogic', () => ({
    businessKnowledgeLogic: {},
}))

function makeSource(overrides: Partial<KnowledgeSource> = {}): KnowledgeSource {
    return {
        id: '11111111-1111-1111-1111-111111111111',
        team_id: 1,
        name: 'Refund policy',
        source_type: 'text',
        is_generated: true,
        status: 'ready',
        error_message: '',
        document_count: 1,
        chunk_count: 3,
        created_at: '2026-09-01T12:00:00Z',
        updated_at: '2026-09-01T12:00:00Z',
        source_url: '',
        last_refresh_at: null,
        last_refresh_status: 'success',
        last_refresh_error: '',
        refresh_interval: 'manual',
        next_refresh_at: null,
        has_unsafe_documents: false,
        embedding_status: 'completed',
        learned_from_ticket_number: 42,
        learned_from_ticket_url: 'https://us.posthog.com/project/1/support/tickets/42',
        crawl_mode: 'single',
        crawl_config: {},
        original_filename: '',
        file_content_type: '',
        file_size_bytes: null,
        always_include: false,
        ...overrides,
    }
}

describe('BusinessKnowledgeScene', () => {
    const openEditModal = jest.fn()

    beforeEach(() => {
        jest.clearAllMocks()
        ;(useActions as jest.Mock).mockReturnValue({
            openCreateModal: jest.fn(),
            openEditModal,
            deleteSource: jest.fn(),
            refreshSource: jest.fn(),
        })
        ;(useValues as jest.Mock).mockReturnValue({
            sources: [makeSource()],
            sourcesLoading: false,
            readyCount: 1,
            totalChunks: 3,
            refreshingIds: [],
        })
    })

    afterEach(() => {
        cleanup()
    })

    it('lets you open the editor for a learned source', () => {
        render(<BusinessKnowledgeScene />)

        expect(screen.getByText('Learned from ticket #42')).toBeInTheDocument()
        expect(screen.getByText('Learned from ticket #42').closest('a')).toHaveAttribute(
            'href',
            '/project/1/support/tickets/42'
        )
        expect(screen.getByText('Learned')).toBeInTheDocument()
        expect(screen.getByLabelText('Edit')).toBeInTheDocument()
        expect(screen.getByLabelText('Delete')).toBeInTheDocument()

        fireEvent.click(screen.getByText('Refund policy'))

        expect(openEditModal).toHaveBeenCalledWith(expect.objectContaining({ id: makeSource().id }))
    })
})
