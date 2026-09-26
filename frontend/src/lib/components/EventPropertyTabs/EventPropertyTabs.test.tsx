import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'
import { EventType } from '~/types'

import { EventPropertyTabContent, EventPropertyTabs, TabContentComponentFnProps } from './EventPropertyTabs'

function eventWith(properties: Record<string, any>): EventType {
    return {
        id: 'event-id',
        distinct_id: 'distinct-id',
        event: 'custom_event',
        timestamp: '2026-09-18T00:00:00.000Z',
        properties,
        elements: [],
    } as EventType
}

function tabContent({ properties, tabKey }: TabContentComponentFnProps): JSX.Element {
    return <div data-attr={`tab-content-${tabKey}`}>{Object.keys(properties).join(' ')}</div>
}

describe('EventPropertyTabs', () => {
    afterEach(() => cleanup())

    it('falls back to the properties tab when the active tab disappears', async () => {
        initKeaTests()
        const { container, rerender } = render(
            <EventPropertyTabs
                event={eventWith({ plan: 'free', $has_recording: true })}
                tabContentComponentFn={tabContent}
            />
        )

        await userEvent.click(screen.getByText('Debug properties'))
        expect(container.querySelector('[data-attr="tab-content-debug_properties"]')).toBeInTheDocument()

        rerender(<EventPropertyTabs event={eventWith({ plan: 'free' })} tabContentComponentFn={tabContent} />)

        expect(screen.queryByText('Debug properties')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="tab-content-properties"]')).toBeInTheDocument()
    })

    it('names the group instead of rendering an empty table', () => {
        const { container } = render(
            <EventPropertyTabContent tabKey="flags" properties={{}}>
                <div data-attr="flags-table" />
            </EventPropertyTabContent>
        )

        expect(screen.getByText('This event has no feature flag properties.')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="flags-table"]')).not.toBeInTheDocument()
    })
})
