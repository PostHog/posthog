import { render } from '@testing-library/react'

import { ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { platformAlertConfigurationActivityDescriber } from './platformAlertConfigurationActivityDescriber'

const logItem = (activity: string, context: Record<string, unknown>): ActivityLogItem => ({
    activity,
    created_at: '2026-11-11T10:00:00Z',
    scope: 'PlatformAlertConfiguration',
    item_id: 'alert-uuid',
    detail: { merge: null, trigger: null, changes: null, name: 'Signups dropped', context: context as any },
})

describe('platformAlertConfigurationActivityDescriber', () => {
    test.each([
        [
            'an insight alert links its insight',
            logItem('created', { source_kind: 'insight', source_id: 'abc123', source_name: 'Signups' }),
            'created the alert Signups dropped on insight Signups',
            ['/insights/abc123'],
        ],
        [
            'a deleted insight alert still links its insight',
            logItem('deleted', { source_kind: 'insight', source_id: 'abc123', source_name: 'Signups' }),
            'deleted the alert Signups dropped on insight Signups',
            ['/insights/abc123'],
        ],
        [
            'a logs alert links its page',
            logItem('created', { source_kind: 'logs' }),
            'created the logs alert Signups dropped',
            ['/logs/alerts/alert-uuid'],
        ],
        [
            'a deleted logs alert links nothing',
            logItem('deleted', { source_kind: 'logs' }),
            'deleted the logs alert',
            [],
        ],
    ])('%s', (_name, item, text, hrefs) => {
        const { container } = render(<>{platformAlertConfigurationActivityDescriber(item).description}</>)

        expect(container.textContent).toContain(text)
        expect(
            Array.from(container.querySelectorAll('a')).map((link) => new URL(link.href, 'http://x').pathname)
        ).toEqual(hrefs.map((href) => expect.stringContaining(href)))
    })
})
