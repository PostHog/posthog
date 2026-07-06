import { render } from '@testing-library/react'

import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'

import { instanceSettingActivityDescriber } from './instanceSettingActivityDescriber'

const makeLogItem = (field: string, before: unknown, after: unknown, activity = 'updated'): ActivityLogItem => ({
    user: { first_name: 'Ada', last_name: 'Lovelace', email: 'ada@posthog.com' },
    activity,
    created_at: '2026-06-04T00:00:00Z',
    scope: ActivityScope.INSTANCE_SETTING,
    item_id: field,
    detail: {
        merge: null,
        trigger: null,
        name: field,
        changes: [
            {
                type: ActivityScope.INSTANCE_SETTING,
                action: 'changed',
                field,
                before: before as ActivityChange['before'],
                after: after as ActivityChange['after'],
            },
        ],
    },
})

const describedText = (item: ActivityLogItem): string => {
    const { description } = instanceSettingActivityDescriber(item)
    if (!description) {
        return ''
    }
    const { container } = render(description as JSX.Element)
    return container.textContent || ''
}

describe('instanceSettingActivityDescriber', () => {
    it('renders a non-secret boolean change with both values', () => {
        const text = describedText(makeLogItem('AUTO_START_ASYNC_MIGRATIONS', false, true))
        expect(text).toContain('changed instance setting AUTO_START_ASYNC_MIGRATIONS from false to true')
    })

    it('renders a non-secret string change with both values verbatim', () => {
        const text = describedText(makeLogItem('GITHUB_APP_SLUG', '', 'posthog-app'))
        expect(text).toContain('changed instance setting GITHUB_APP_SLUG from "" to "posthog-app"')
    })

    // Each secret transition must render its verb and never echo the raw sentinels. The
    // `<unset>` → `<unset>` pair has no mapped verb and must render "updated" rather than
    // falling through to the cleartext "changed … from … to …" branch.
    it.each([
        ['set', '<unset>', '<redacted>'],
        ['rotated', '<redacted>', '<redacted>'],
        ['cleared', '<redacted>', '<unset>'],
        ['updated', '<unset>', '<unset>'],
    ])('renders a secret %s transition without leaking sentinels', (verb, before, after) => {
        const text = describedText(makeLogItem('EMAIL_HOST_PASSWORD', before, after))
        expect(text).toContain(`${verb} instance setting EMAIL_HOST_PASSWORD`)
        expect(text).not.toContain('<redacted>')
        expect(text).not.toContain('<unset>')
        expect(text).not.toContain('changed instance setting')
    })

    it('falls through to the default describer for non-updated activity', () => {
        // A "created" activity has no before/after transition; the describer must
        // hand off to the default describer rather than render a "changed" line.
        const text = describedText(makeLogItem('SOME_KEY', null, true, 'created'))
        expect(text).toContain('created')
        expect(text).not.toContain('changed instance setting')
    })
})
