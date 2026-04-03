import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import { PersonActorType, SessionActorType } from '~/types'

import { SessionActorDisplay } from './SessionActorDisplay'

describe('SessionActorDisplay', () => {
    const baseSession: SessionActorType = {
        type: 'session',
        id: 'session-abc-123',
        properties: {},
        created_at: '2024-06-15T10:30:00Z',
        matched_recordings: [],
        value_at_data_point: null,
    }

    it('renders session timestamp', () => {
        render(<SessionActorDisplay actor={baseSession} />)
        expect(screen.getByText(/Jun 15/)).toBeInTheDocument()
    })

    it('renders session duration when available', () => {
        const actor: SessionActorType = {
            ...baseSession,
            properties: { $session_duration: 222 },
        }
        render(<SessionActorDisplay actor={actor} />)
        expect(screen.getByText(/3m 42s/)).toBeInTheDocument()
    })

    it('renders person display name when person data is available', () => {
        const actor: SessionActorType = {
            ...baseSession,
            person: {
                type: 'person',
                id: 'person-1',
                distinct_ids: ['user@example.com'],
                is_identified: true,
                properties: { email: 'user@example.com', name: 'Test User' },
                created_at: '2024-01-01',
                matched_recordings: [],
                value_at_data_point: null,
            },
        }
        render(<SessionActorDisplay actor={actor} />)
        // asDisplay resolves email first per PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
        expect(screen.getAllByText('user@example.com').length).toBeGreaterThan(0)
    })

    it('renders "Anonymous" when no person data', () => {
        const actor: SessionActorType = {
            ...baseSession,
            person: {} as PersonActorType,
        }
        render(<SessionActorDisplay actor={actor} />)
        expect(screen.getByText('Anonymous')).toBeInTheDocument()
    })

    it('renders "Unknown time" when no created_at', () => {
        const actor: SessionActorType = {
            ...baseSession,
            created_at: '',
        }
        render(<SessionActorDisplay actor={actor} />)
        expect(screen.getByText('Unknown time')).toBeInTheDocument()
    })
})
