import { cleanup, render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { withTimezone } from '../../shared/testTimezone'
import { FirstSeenCell } from './FirstSeenCell'

describe('FirstSeenCell', () => {
    afterEach(cleanup)

    it('shows the first seen date in the project timezone, the calendar of the checked date', () => {
        withTimezone('America/Los_Angeles', () => {
            initKeaTests()
            const { container } = render(
                <FirstSeenCell
                    load={{
                        status: 'ready',
                        value: { firstSeen: '2026-08-02T00:30:00Z', checkedFrom: '2026-08-02', isNew: true },
                    }}
                    timezone="UTC"
                />
            )

            expect(container.textContent?.trim()).toEqual('Aug 2, 2026')
        })
    })
})
