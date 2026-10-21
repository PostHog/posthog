import { render } from '@testing-library/react'

import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { initKeaTests } from '~/test/init'
import { ActivityScope } from '~/types'

import { dataWarehouseSavedQueryActivityDescriber } from './activityDescriptions'

function describeText(changes: ActivityChange[]): string {
    const logItem: ActivityLogItem = {
        user: { first_name: 'Max', last_name: 'Hog', email: 'max@posthog.com' },
        activity: 'updated',
        created_at: '2026-03-01T00:00:00Z',
        scope: ActivityScope.DATA_WAREHOUSE_SAVED_QUERY,
        item_id: '7',
        detail: { name: 'daily view', changes, merge: null, trigger: null },
    }
    const { description } = dataWarehouseSavedQueryActivityDescriber(logItem)
    const { container } = render(<>{description}</>)
    return container.textContent ?? ''
}

const change = (field: string, before: unknown, after: unknown): ActivityChange => ({
    type: ActivityScope.DATA_WAREHOUSE_SAVED_QUERY,
    action: 'changed',
    field,
    before: before as ActivityChange['before'],
    after: after as ActivityChange['after'],
})

describe('dataWarehouseSavedQueryActivityDescriber', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each([
        ['column_order', ['id', 'name'], ['name', 'id'], 'reordered 2 columns'],
        ['folder', null, 'folder-1', 'moved the view to the folder-1 folder'],
        ['folder', 'folder-1', null, 'removed the view from its folder'],
        ['is_test', false, true, 'marked the view as a test view'],
        ['is_test', true, false, 'unmarked the view as a test view'],
        ['new_field', 'before', 'after', 'changed new field'],
    ])('describes %s changes', (field, before, after, expected) => {
        expect(describeText([change(field, before, after)])).toContain(expected)
    })

    it.each([
        [
            null,
            { enabled: true, incremental_key: 'day', unique_key: ['id'], lookback_seconds: 3600 },
            'enabled incremental materialization with incremental key day, unique key id, lookback 1 hour',
        ],
        [{}, { enabled: true, incremental_key: 'day' }, 'enabled incremental materialization'],
        [
            { enabled: true, incremental_key: 'day', unique_key: ['id'], lookback_seconds: 3600 },
            null,
            'disabled incremental materialization',
        ],
        [{ enabled: true, incremental_key: 'day' }, {}, 'disabled incremental materialization'],
        [
            { enabled: true, incremental_key: 'day', unique_key: ['id'] },
            { enabled: false, incremental_key: 'day', unique_key: ['id'] },
            'disabled incremental materialization',
        ],
        [
            { enabled: false, incremental_key: 'day', unique_key: ['id'] },
            { enabled: true, incremental_key: 'day', unique_key: ['id'] },
            'enabled incremental materialization with incremental key day, unique key id',
        ],
        [
            { enabled: true, incremental_key: 'day', lookback_seconds: 3600 },
            { enabled: true, incremental_key: 'hour', lookback_seconds: 7200 },
            'updated incremental materialization settings: incremental key from day to hour, lookback from 1 hour to 2 hours',
        ],
    ])('describes incremental materialization transitions', (before, after, expected) => {
        expect(describeText([change('incremental_config', before, after)])).toContain(expected)
    })

    it('keeps the existing activity branches', () => {
        expect(describeText([change('sync_frequency_interval', '0:01:00', '1:00:00')])).toContain(
            'changed sync frequency from 1 minute to 1 hour'
        )
        expect(describeText([change('is_materialized', false, true)])).toContain('enabled materialization')
        expect(describeText([change('query', { query: 'SELECT 1' }, { query: 'SELECT 2' })])).toContain(
            'updated the query'
        )
    })
})
