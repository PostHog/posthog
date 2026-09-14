import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'
import { LiveEvent } from '~/types'

import { LiveEventsFeed } from './LiveEventsFeed'
import { LiveStreamError } from './liveEventsLogic'

const EVENT_FROM_BEFORE_THE_BREAK: LiveEvent = {
    uuid: '0194f000-0000-7000-8000-000000000001',
    event: '$pageview',
    properties: { $current_url: 'https://example.com/pricing' },
    timestamp: '2026-01-01T00:00:00.000Z',
    team_id: 1,
    distinct_id: 'visitor-1',
    created_at: '2026-01-01T00:00:00.000Z',
}

const FATAL_ERROR: LiveStreamError = {
    message: 'The live event stream failed with error 504. Try again, and contact us if it keeps happening.',
    retrying: false,
}

const TRANSPORT_ERROR: LiveStreamError = {
    message: 'Lost the connection to the live event stream. Trying to reconnect.',
    retrying: true,
}

describe('LiveEventsFeed', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('offers a retry above rows kept from before a fatal break', async () => {
        const onRetry = jest.fn()
        render(
            <Provider>
                <LiveEventsFeed
                    events={[EVENT_FROM_BEFORE_THE_BREAK]}
                    columns={['url']}
                    streamError={FATAL_ERROR}
                    onRetry={onRetry}
                />
            </Provider>
        )

        expect(screen.getByText(FATAL_ERROR.message)).toBeInTheDocument()
        await userEvent.click(screen.getAllByText('Try again')[0])
        expect(onRetry).toHaveBeenCalledTimes(1)
    })

    it('reports a reconnect above the rows without offering a retry', () => {
        render(
            <Provider>
                <LiveEventsFeed
                    events={[EVENT_FROM_BEFORE_THE_BREAK]}
                    columns={['url']}
                    streamError={TRANSPORT_ERROR}
                    onRetry={jest.fn()}
                />
            </Provider>
        )

        expect(screen.getByText(TRANSPORT_ERROR.message)).toBeInTheDocument()
        expect(screen.queryByText('Try again')).not.toBeInTheDocument()
    })

    it('says nothing about the stream while it is paused', () => {
        render(
            <Provider>
                <LiveEventsFeed
                    events={[EVENT_FROM_BEFORE_THE_BREAK]}
                    columns={['url']}
                    streamPaused
                    streamError={FATAL_ERROR}
                />
            </Provider>
        )

        expect(screen.queryByText(FATAL_ERROR.message)).not.toBeInTheDocument()
    })
})
