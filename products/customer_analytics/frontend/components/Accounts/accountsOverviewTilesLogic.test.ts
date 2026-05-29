import {
    AccountsOverviewTile,
    buildOverviewHogqlQuery,
    isNumericColumnType,
    numericColumnOptions,
    OverviewFilters,
    parseTileValues,
    stripHogqlAlias,
} from './accountsOverviewTilesLogic'

const EMPTY_FILTERS: OverviewFilters = {
    searchQuery: '',
    tagsFilter: [],
    allRolesUnassigned: false,
    csmFilter: null,
    accountExecutiveFilter: null,
    accountOwnerFilter: null,
}

describe('stripHogqlAlias', () => {
    it('strips a trailing AS alias', () => {
        expect(stripHogqlAlias('accounts.health.score AS score')).toBe('accounts.health.score')
    })

    it('leaves a plain expression untouched', () => {
        expect(stripHogqlAlias('health_score')).toBe('health_score')
    })

    it('does not strip AS in the middle', () => {
        expect(stripHogqlAlias("toString(JSONExtract(properties, 'score', 'Nullable(Int64)'))")).toBe(
            "toString(JSONExtract(properties, 'score', 'Nullable(Int64)'))"
        )
    })
})

describe('isNumericColumnType', () => {
    it('accepts numeric types', () => {
        expect(isNumericColumnType('integer')).toBe(true)
        expect(isNumericColumnType('float')).toBe(true)
        expect(isNumericColumnType('decimal')).toBe(true)
    })

    it('rejects non-numeric types', () => {
        expect(isNumericColumnType('string')).toBe(false)
        expect(isNumericColumnType('boolean')).toBe(false)
        expect(isNumericColumnType(undefined)).toBe(false)
    })
})

describe('numericColumnOptions', () => {
    it('keeps numeric direct columns and strips aliases on join columns', () => {
        const options = numericColumnOptions([
            {
                key: 'account_properties',
                label: 'Account properties',
                options: [
                    { name: 'name', expression: 'name', type: 'string' },
                    { name: 'health_score', expression: 'health_score', type: 'integer' },
                ],
            },
            {
                key: 'accounts.health',
                label: 'health',
                options: [{ name: 'score', expression: 'accounts.health.score AS score', type: 'float' }],
            },
            { key: 'sql_expression', label: 'SQL expression', options: [], isFreeform: true },
        ])
        expect(options).toEqual([
            { name: 'health_score', expression: 'health_score', type: 'integer' },
            { name: 'score', expression: 'accounts.health.score', type: 'float' },
        ])
    })
})

describe('buildOverviewHogqlQuery', () => {
    const tiles: AccountsOverviewTile[] = [
        { id: 'a', label: 'Accounts', metric: { type: 'count' } },
        {
            id: 'b',
            label: 'Sum',
            metric: { type: 'sum', columnExpression: 'health_score', columnLabel: 'Health score' },
        },
        {
            id: 'c',
            label: 'Avg',
            metric: { type: 'avg', columnExpression: 'health_score', columnLabel: 'Health score' },
        },
        {
            id: 'd',
            label: 'At risk',
            metric: {
                type: 'count_threshold',
                columnExpression: 'health_score',
                columnLabel: 'Health score',
                operator: '<',
                value: 6,
            },
        },
    ]

    it('returns null when there are no tiles', () => {
        expect(buildOverviewHogqlQuery([], EMPTY_FILTERS)).toBeNull()
    })

    it('builds a select with one column per tile and aliases FROM as accounts', () => {
        const result = buildOverviewHogqlQuery(tiles, EMPTY_FILTERS)
        expect(result?.query).toBe(
            'SELECT count() AS tile_a, sum(health_score) AS tile_b, avg(health_score) AS tile_c, ' +
                'countIf(health_score < 6) AS tile_d FROM system.accounts AS accounts'
        )
    })

    it('escapes single quotes in the search filter', () => {
        const result = buildOverviewHogqlQuery(tiles.slice(0, 1), { ...EMPTY_FILTERS, searchQuery: "O'Reilly" })
        expect(result?.query).toContain("name ILIKE '%O\\'Reilly%'")
        expect(result?.query).toContain("external_id ILIKE '%O\\'Reilly%'")
    })

    it('emits a tags subquery when tagsFilter is set', () => {
        const result = buildOverviewHogqlQuery(tiles.slice(0, 1), { ...EMPTY_FILTERS, tagsFilter: ['enterprise'] })
        expect(result?.query).toContain('FROM system._account_tagged_items AS ti')
        expect(result?.query).toContain("t.name IN ('enterprise')")
    })

    it('applies role filters and all-unassigned together', () => {
        const result = buildOverviewHogqlQuery(tiles.slice(0, 1), {
            ...EMPTY_FILTERS,
            csmFilter: 42,
            allRolesUnassigned: true,
        })
        expect(result?.query).toContain("JSONExtract(properties, 'csm', 'id', 'Nullable(Int64)') = 42")
        expect(result?.query).toContain("isNull(JSONExtract(properties, 'csm', 'id', 'Nullable(Int64)'))")
        expect(result?.query).toContain("isNull(JSONExtract(properties, 'account_executive', 'id', 'Nullable(Int64)'))")
        expect(result?.query).toContain("isNull(JSONExtract(properties, 'account_owner', 'id', 'Nullable(Int64)'))")
    })
})

describe('parseTileValues', () => {
    const tiles: AccountsOverviewTile[] = [
        { id: 'a', label: 'Accounts', metric: { type: 'count' } },
        {
            id: 'b',
            label: 'Sum',
            metric: { type: 'sum', columnExpression: 'health_score', columnLabel: 'Health score' },
        },
    ]

    it('zips by column alias when columns are present', () => {
        expect(parseTileValues({ columns: ['tile_b', 'tile_a'], results: [[7.5, 42]] }, tiles)).toEqual({
            a: 42,
            b: 7.5,
        })
    })

    it('falls back to row order when columns are missing', () => {
        expect(parseTileValues({ results: [[42, 7.5]] }, tiles)).toEqual({ a: 42, b: 7.5 })
    })

    it('returns null for tiles whose alias is not in the response', () => {
        expect(parseTileValues({ columns: ['tile_a'], results: [[42]] }, tiles)).toEqual({ a: null, b: null })
    })

    it('returns null for missing or malformed values', () => {
        expect(parseTileValues({ columns: ['tile_a', 'tile_b'], results: [[null, 'not a number']] }, tiles)).toEqual({
            a: null,
            b: null,
        })
    })

    it('returns all-nulls when results is missing or empty', () => {
        expect(parseTileValues(null, tiles)).toEqual({ a: null, b: null })
        expect(parseTileValues({ results: [] }, tiles)).toEqual({ a: null, b: null })
    })
})
