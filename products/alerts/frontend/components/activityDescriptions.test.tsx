import { render } from '@testing-library/react'

import { ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { initKeaTests } from '~/test/init'
import { ActivityScope } from '~/types'

import { alertConfigurationActivityDescriber } from './activityDescriptions'

describe('alert ownership activity descriptions', () => {
    beforeEach(() => initKeaTests())

    it.each([
        ['transferred_ownership', 'sam@example.com', 'transferred ownership of the alert', 'sam@example.com'],
        ['took_ownership', 'previous-email@example.com', 'took ownership of the alert', null],
        ['took_ownership', undefined, 'took ownership of the alert', null],
    ])('describes ownership assigned to %s', (activity, email, action, recipient) => {
        const logItem: ActivityLogItem = {
            user: { first_name: 'Alex', last_name: '', email: 'alex@example.com' },
            activity,
            created_at: '2026-01-01T00:00:00Z',
            scope: 'AlertConfiguration',
            detail: {
                name: 'Weekly alert',
                merge: null,
                trigger: null,
                changes: email
                    ? [
                          {
                              type: ActivityScope.ALERT_CONFIGURATION,
                              action: 'changed',
                              field: 'created_by',
                              after: { id: 2, email },
                          },
                      ]
                    : [],
            },
        }
        const result = alertConfigurationActivityDescriber(logItem)
        const { container } = render(<>{result.description}</>)
        expect(container.textContent).toBe(`Alex ${action} Weekly alert${recipient ? ` to ${recipient}` : ''}`)
        const summary = render(<>{result.summary?.action}</>)
        expect(summary.container.textContent?.toLowerCase()).toBe(action)
    })
})
