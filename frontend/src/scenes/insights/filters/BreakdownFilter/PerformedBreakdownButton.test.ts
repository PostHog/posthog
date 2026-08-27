import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { performedBreakdownHogQL } from './PerformedBreakdownButton'

describe('performedBreakdownHogQL', () => {
    it.each([
        ['escapes quotes in event names', "sign'up", TaxonomicFilterGroupType.Events, "sign'up", "event = 'sign\\'up'"],
        ['matches actions by id', 42, TaxonomicFilterGroupType.Actions, 'My action', 'matchesAction(42)'],
    ])('%s', (_name, value, groupType, label, expectedMatch) => {
        const expr = performedBreakdownHogQL(value, groupType, label)
        expect(expr).toBe(
            `if(person_id IN (SELECT person_id FROM events WHERE ${expectedMatch} AND timestamp > now() - INTERVAL 30 DAY), ` +
                `'Did perform', 'Did not perform') -- Performed ${label}`
        )
    })
})
