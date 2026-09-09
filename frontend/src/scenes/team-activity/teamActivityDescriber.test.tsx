import { render } from '@testing-library/react'

import { ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'

import { teamActivityDescriber } from './teamActivityDescriber'

describe('teamActivityDescriber', () => {
    const extraSettingsUpdate = (before: Record<string, any>, after: Record<string, any>): ActivityLogItem => ({
        activity: 'updated',
        created_at: '2026-06-04T00:00:00Z',
        scope: ActivityScope.TEAM,
        user: { first_name: 'Ada', last_name: 'Lovelace', email: 'ada@posthog.com' },
        detail: {
            merge: null,
            trigger: null,
            name: 'Default project',
            changes: [{ type: ActivityScope.TEAM, action: 'changed', field: 'extra_settings', before, after }],
        },
    })

    const describedText = (before: Record<string, any>, after: Record<string, any>): string =>
        render(<>{teamActivityDescriber(extraSettingsUpdate(before, after)).description}</>).container.textContent ?? ''

    it.each([
        ['turned off', {}, { sample_data_opt_out: true }, 'disabled sample charts before the first event'],
        [
            'turned back on',
            { sample_data_opt_out: true },
            { sample_data_opt_out: false },
            'enabled sample charts before the first event',
        ],
        [
            'dropped from the settings',
            { sample_data_opt_out: true },
            {},
            'enabled sample charts before the first event',
        ],
    ])('describes the sample charts setting being %s', (_name, before, after, expected) => {
        expect(describedText(before, after)).toContain(expected)
    })

    it.each([
        [
            'another setting changes and the opt-out rides along unchanged',
            { sample_data_opt_out: true, person_last_seen_at_enabled: false },
            { sample_data_opt_out: true, person_last_seen_at_enabled: true },
        ],
        ['the opt-out is resent with the same value', { sample_data_opt_out: false }, { sample_data_opt_out: false }],
    ])('does not mention sample charts when %s', (_name, before, after) => {
        expect(describedText(before, after)).not.toContain('sample charts')
    })
})
