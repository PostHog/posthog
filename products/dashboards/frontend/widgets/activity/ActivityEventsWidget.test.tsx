import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { ActivityEventsWidget } from './ActivityEventsWidget'

describe('ActivityEventsWidget', () => {
    afterEach(() => {
        cleanup()
    })

    beforeEach(() => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM })
        teamLogic.mount()
    })

    const event = {
        uuid: 'event-1',
        event: 'file uploaded',
        person: { display_name: 'Alex Chen', id: '1', distinct_id: 'user-1' },
        url: 'https://app.example.test/files',
        lib: 'web',
        timestamp: '2026-05-26T08:00:00.000Z',
    }

    it('renders event rows from the widget result payload', () => {
        render(
            <ActivityEventsWidget
                tileId={1}
                config={{ limit: 10 }}
                loading={false}
                result={{
                    results: [event],
                    hasMore: false,
                    limit: 10,
                    totalCount: 1,
                    totalCountCapped: false,
                }}
            />
        )

        expect(screen.getByText('file uploaded')).toBeInTheDocument()
        expect(screen.getByText('Alex Chen')).toBeInTheDocument()
        expect(screen.getByText('https://app.example.test/files')).toBeInTheDocument()
        expect(screen.getByText('web')).toBeInTheDocument()
        expect(screen.getByText('1 of 1 event')).toBeInTheDocument()
    })

    it('renders an empty state when there are no events', () => {
        const { container } = render(
            <ActivityEventsWidget tileId={1} config={{ limit: 10 }} loading={false} result={{ results: [] }} />
        )

        expect(container.querySelector('[data-attr="activity-events-widget-empty-state"]')).toBeInTheDocument()
        expect(screen.getByText('No events yet')).toBeInTheDocument()
    })
})
