import { getDirectQuerySelectionDescription } from './SchemaForm'

describe('SchemaForm', () => {
    it('describes browsing across all schemas when the schema is blank', () => {
        expect(getDirectQuerySelectionDescription('')).toEqual(
            'Choose which tables should be available for querying in PostHog. You are browsing tables across all non-system schemas, so tables from different schemas appear here with schema-prefixed names.'
        )
    })

    it('describes the selected schema when one is set', () => {
        expect(getDirectQuerySelectionDescription(' public ')).toEqual(
            'Choose which tables should be available for querying in PostHog. You are browsing tables from the "public" schema.'
        )
    })
})
