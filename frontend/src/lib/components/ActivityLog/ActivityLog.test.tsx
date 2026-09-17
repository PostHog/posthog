import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { ActivityLogRow } from 'lib/components/ActivityLog/ActivityLog'
import { HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { dayjs } from 'lib/dayjs'

import { initKeaTests } from '~/test/init'

describe('ActivityLogRow', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('opens an item that has an expanded view on that view', () => {
        const logItem: HumanizedActivityLogItem = {
            name: 'peter',
            description: <>changed the rollout</>,
            created_at: dayjs('2022-02-05T16:28:39.594Z'),
            expandedView: { label: 'Release conditions', content: <div>the release conditions</div> },
        }

        render(
            <Provider>
                <ActivityLogRow logItem={logItem} />
            </Provider>
        )
        fireEvent.click(screen.getByRole('button'))

        expect(screen.getByText('Release conditions').closest('[role="tab"]')).toHaveAttribute('aria-selected', 'true')
        expect(screen.getByText('the release conditions')).toBeInTheDocument()
    })
})
