import { dayjs } from 'lib/dayjs'

import { samplePlaceholderColumn } from '~/queries/nodes/DataTable/sampleRows'

import { buildSampleEventRows } from './sampleEventRows'

const NOW = dayjs('2026-10-23T12:00:00.000Z')
const URL_COLUMN = 'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen'

describe('buildSampleEventRows', () => {
    it('puts each value in the position of its column, whatever the column order', () => {
        const rows = buildSampleEventRows(
            ['timestamp', 'properties.$browser_version', 'event', 'person_display_name -- Person', URL_COLUMN],
            NOW
        )

        expect(rows[0].result).toEqual([
            '2026-10-23T11:59:00.000Z',
            samplePlaceholderColumn,
            '$pageview',
            expect.objectContaining({ display_name: 'alice@example.com' }),
            'https://example.com/pricing',
        ])
    })

    it.each([
        ['count()', samplePlaceholderColumn],
        ['properties.$lib', 'posthog-ios'],
        ['properties.constructor', samplePlaceholderColumn],
        [URL_COLUMN, 'HomeScreen'],
        ['person', expect.objectContaining({ properties: { email: 'carol@example.com' } })],
    ])('fills the %s column of a mobile row', (column, expected) => {
        const mobileRow = buildSampleEventRows([column], NOW)[2]

        expect(mobileRow.result).toEqual([expected])
    })
})
