import { render } from '@testing-library/react'

import { ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { initKeaTests } from '~/test/init'
import { ActivityScope } from '~/types'

import { exportedAssetActivityDescriber } from './activityDescriptions'

function makeLogItem(overrides: Partial<ActivityLogItem> & { detail: ActivityLogItem['detail'] }): ActivityLogItem {
    return {
        user: { first_name: 'Max', last_name: 'Hog', email: 'max@posthog.com' },
        activity: 'exported',
        created_at: '2026-03-01T00:00:00Z',
        scope: ActivityScope.EXPORTED_ASSET,
        item_id: 'abc-123',
        ...overrides,
    }
}

function describeText(logItem: ActivityLogItem, asNotification?: boolean): string {
    const { description } = exportedAssetActivityDescriber(logItem, asNotification)
    if (!description) {
        return ''
    }
    const { container } = render(<>{description}</>)
    return container.textContent ?? ''
}

describe('exported asset activity descriptions', () => {
    beforeEach(() => {
        // The describer returns JSX containing <Link> components which rely on kea-router
        initKeaTests()
    })

    it('describes a dashboard export with its format', () => {
        const text = describeText(
            makeLogItem({
                detail: {
                    name: 'Weekly metrics',
                    changes: [
                        { type: 'ExportedAsset', action: 'exported', field: 'export_format', after: 'image/png' },
                    ],
                },
            })
        )
        expect(text).toBe('Max Hog exported Weekly metrics as a png')
    })

    it('describes a SQL query export', () => {
        const text = describeText(
            makeLogItem({
                detail: {
                    name: 'SQL query results',
                    changes: [{ type: 'ExportedAsset', action: 'exported', field: 'export_format', after: 'text/csv' }],
                },
            })
        )
        expect(text).toBe('Max Hog exported SQL query results as a csv')
    })

    it('prefixes with "your" when rendered as a notification', () => {
        const text = describeText(
            makeLogItem({
                detail: {
                    name: 'Weekly metrics',
                    changes: [
                        { type: 'ExportedAsset', action: 'exported', field: 'export_format', after: 'image/png' },
                    ],
                },
            }),
            true
        )
        expect(text).toBe('Max Hog exported your Weekly metrics as a png')
    })

    it('falls back gracefully when name and format are missing', () => {
        const text = describeText(makeLogItem({ detail: { name: undefined, changes: [] } }))
        expect(text).toBe('Max Hog exported an export as an export')
    })

    it('uses the raw format when it has no slash', () => {
        const text = describeText(
            makeLogItem({
                detail: {
                    name: 'an export',
                    changes: [{ type: 'ExportedAsset', action: 'exported', field: 'export_format', after: 'csv' }],
                },
            })
        )
        expect(text).toBe('Max Hog exported an export as a csv')
    })

    it('returns no description for a non-export scope', () => {
        const { description } = exportedAssetActivityDescriber(
            makeLogItem({ scope: ActivityScope.INSIGHT, detail: { name: 'x', changes: [] } })
        )
        expect(description).toBeNull()
    })

    it('delegates unknown activities to the default describer', () => {
        const text = describeText(makeLogItem({ activity: 'deleted', detail: { name: 'Weekly metrics', changes: [] } }))
        expect(text).not.toContain('exported')
    })
})
