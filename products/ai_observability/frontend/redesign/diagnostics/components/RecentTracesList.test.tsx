import { cleanup, render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { makeTraceListItem, makeTracePreview, ready } from '../../traces/testFixtures'
import { RecentTracesList } from './RecentTracesList'

describe('RecentTracesList', () => {
    afterEach(cleanup)

    it('keeps a prompt out of autocapture, so copying it sends no text', () => {
        initKeaTests()
        const { getByText } = render(
            <RecentTracesList
                traces={ready([makeTraceListItem({ id: 'trace-1' })])}
                previews={new Map([['trace-1', ready(makeTracePreview('trace-1', { input: 'Refund my order' }))]])}
                emptyMessage="No traces"
                inputFailedMessage="Couldn't load the input."
                onRetry={() => {}}
                onOpenTrace={() => {}}
                data-attr="tool-drawer"
            />
        )

        expect(getByText('Refund my order').closest('.ph-no-capture')).not.toBeNull()
    })
})
