import { NodeKind } from '~/queries/schema/schema-general'

import {
    AccountsOverviewTile,
    buildOverviewAccountsQuery,
    isNumericColumnType,
    numericColumnOptions,
    OverviewFilters,
    parseTileValues,
    stripHogqlAlias,
    tileMetricExpression,
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

describe('tileMetricExpression', () => {
    it('produces the right HogQL fragment per metric type', () => {
        expect(tileMetricExpression({ id: 'x', label: 'l', metric: { type: 'count' } })).toBe('count()')
        expect(
            tileMetricExpression({
                id: 'x',
                label: 'l',
                metric: { type: 'sum', columnExpression: 'health_score', columnLabel: 'Health score' },
            })
        ).toBe('sum(health_score)')
        expect(
            tileMetricExpression({
                id: 'x',
                label: 'l',
                metric: { type: 'avg', columnExpression: 'health_score', columnLabel: 'Health score' },
            })
        ).toBe('avg(health_score)')
        expect(
            tileMetricExpression({
                id: 'x',
                label: 'l',
                metric: {
                    type: 'count_threshold',
                    columnExpression: 'health_score',
                    columnLabel: 'Health score',
                    operator: '<',
                    value: 6,
                },
            })
        ).toBe('countIf(health_score < 6)')
    })
})

describe('buildOverviewAccountsQuery', () => {
    const tiles: AccountsOverviewTile[] = [
        { id: 'a', label: 'Accounts', metric: { type: 'count' } },
        {
            id: 'b',
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
        expect(buildOverviewAccountsQuery([], EMPTY_FILTERS)).toBeNull()
    })

    it('emits an AccountsQuery in metrics mode with one expression per tile', () => {
        expect(buildOverviewAccountsQuery(tiles, EMPTY_FILTERS)).toMatchObject({
            kind: NodeKind.AccountsQuery,
            metrics: ['count()', 'countIf(health_score < 6)'],
            select: [],
        })
    })

    it('forwards filter fields onto the AccountsQuery so the runner reuses its WHERE logic', () => {
        const result = buildOverviewAccountsQuery(tiles, {
            ...EMPTY_FILTERS,
            searchQuery: '  acme  ',
            tagsFilter: ['enterprise'],
            csmFilter: 42,
            allRolesUnassigned: true,
        })
        expect(result).toMatchObject({
            search: 'acme',
            tagNames: ['enterprise'],
            csm: 42,
            allRolesUnassigned: true,
        })
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

    function responseWith(metricsResults: (number | null)[] | undefined): any {
        return {
            kind: NodeKind.AccountsQuery,
            results: [],
            columns: [],
            types: [],
            hogql: '',
            limit: 0,
            offset: 0,
            metricsResults,
        }
    }

    it('reads metric values in tile order', () => {
        expect(parseTileValues(responseWith([42, 7.5]), tiles)).toEqual({ a: 42, b: 7.5 })
    })

    it('returns null when metricsResults is missing or malformed', () => {
        expect(parseTileValues(null, tiles)).toEqual({ a: null, b: null })
        expect(parseTileValues(responseWith(undefined), tiles)).toEqual({ a: null, b: null })
        expect(parseTileValues(responseWith([null, null]), tiles)).toEqual({ a: null, b: null })
    })
})
