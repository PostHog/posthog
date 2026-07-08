import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import {
    accountsOverviewTilesLogic,
    AccountsOverviewTile,
    isNumericColumnType,
    isTileClickable,
    numericColumnOptions,
    parseTileValues,
    stripHogqlAlias,
    tileFilterFor,
    tileMetricExpression,
    tileToRowFilter,
} from './accountsOverviewTilesLogic'
import {
    ACCOUNTS_OVERVIEW_LEGACY_TILES_PREFIX,
    AccountsEvents,
    DEFAULT_TILES,
    MAX_ACCOUNTS_OVERVIEW_TILES,
} from './constants'

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

    it('accepts numeric custom-property display types', () => {
        expect(isNumericColumnType('number')).toBe(true)
        expect(isNumericColumnType('currency')).toBe(true)
        expect(isNumericColumnType('percent')).toBe(true)
    })

    it('rejects non-numeric types', () => {
        expect(isNumericColumnType('string')).toBe(false)
        expect(isNumericColumnType('boolean')).toBe(false)
        expect(isNumericColumnType('text')).toBe(false)
        expect(isNumericColumnType('date')).toBe(false)
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

    it('includes numeric custom properties and casts their string value for aggregation', () => {
        const options = numericColumnOptions([
            {
                key: 'custom_properties',
                label: 'Custom properties',
                options: [
                    { name: 'Seats', expression: 'accounts.custom_properties.values.`abc` AS cp_abc', type: 'number' },
                    { name: 'Plan', expression: 'accounts.custom_properties.values.`def` AS cp_def', type: 'text' },
                ],
            },
        ])
        expect(options).toEqual([
            {
                name: 'Seats',
                type: 'number',
                expression: 'toFloatOrNull(accounts.custom_properties.values.`abc`)',
            },
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

describe('tileToRowFilter / isTileClickable', () => {
    const thresholdTile: AccountsOverviewTile = {
        id: 'b',
        label: 'At risk',
        metric: {
            type: 'count_threshold',
            columnExpression: 'health_score',
            columnLabel: 'Health score',
            operator: '<',
            value: 6,
        },
    }

    it('maps a threshold tile to its row predicate', () => {
        expect(tileToRowFilter(thresholdTile)).toBe('health_score < 6')
        expect(isTileClickable(thresholdTile)).toBe(true)
    })

    it('returns null for non-threshold tiles', () => {
        const countTile: AccountsOverviewTile = { id: 'a', label: 'Accounts', metric: { type: 'count' } }
        expect(tileToRowFilter(countTile)).toBeNull()
        expect(isTileClickable(countTile)).toBe(false)
    })
})

describe('tileFilterFor', () => {
    it('maps a threshold tile to its active filter descriptor', () => {
        expect(
            tileFilterFor({
                id: 'b',
                label: 'At risk',
                metric: {
                    type: 'count_threshold',
                    columnExpression: 'health_score',
                    columnLabel: 'Health score',
                    operator: '<',
                    value: 6,
                },
            })
        ).toEqual({ tileId: 'b', expression: 'health_score < 6' })
    })

    it('returns null when the tile is not a row-level predicate', () => {
        expect(tileFilterFor({ id: 'a', label: 'Accounts', metric: { type: 'count' } })).toBeNull()
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

describe('addTile limit', () => {
    let logic: ReturnType<typeof accountsOverviewTilesLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = accountsOverviewTilesLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    // addTile is a pure reducer — assert synchronously. toFinishAllListeners() would
    // wait on the connected logics' on-mount loaders (a global pending-promise map),
    // which made this flaky whenever those XHRs were slow to settle.
    it(`stops adding tiles once ${MAX_ACCOUNTS_OVERVIEW_TILES} exist`, () => {
        for (let i = 0; i < MAX_ACCOUNTS_OVERVIEW_TILES + 2; i++) {
            logic.actions.addTile({ label: `Tile ${i}`, metric: { type: 'count' } })
        }
        expect(logic.values.tiles).toHaveLength(MAX_ACCOUNTS_OVERVIEW_TILES)
    })
})

describe('accountsOverviewTilesLogic setTiles', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('replaces the entire tile set', async () => {
        const logic = accountsOverviewTilesLogic()
        logic.mount()
        const tiles = [
            { id: 'a', label: 'A', metric: { type: 'count' as const } },
            { id: 'b', label: 'B', metric: { type: 'count' as const } },
        ]
        await expectLogic(logic, () => logic.actions.setTiles(tiles)).toMatchValues({ tiles })
    })
})

describe('accountsOverviewTilesLogic legacy localStorage tiles (read-only + tombstone)', () => {
    const LEGACY_KEY = `${ACCOUNTS_OVERVIEW_LEGACY_TILES_PREFIX}.scenes.customerAnalytics.accounts.accountsOverviewTilesLogic.tiles`
    const customTiles: AccountsOverviewTile[] = [{ id: 'legacy', label: 'Legacy', metric: { type: 'count' as const } }]

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
    })

    afterEach(() => {
        localStorage.clear()
        jest.restoreAllMocks()
    })

    it('reads a pre-existing custom value on mount, emits a tombstone, and never writes it back', async () => {
        localStorage.setItem(LEGACY_KEY, JSON.stringify(customTiles))
        const logic = accountsOverviewTilesLogic()
        logic.mount()
        await expectLogic(logic).toMatchValues({ tiles: customTiles })
        expect(posthog.capture).toHaveBeenCalledWith(AccountsEvents.OverviewTilesLocalStorageRead, { tile_count: 1 })

        // never writes: changing tiles must not update or recreate the legacy key
        logic.actions.setTiles([{ id: 'x', label: 'X', metric: { type: 'count' as const } }])
        expect(JSON.parse(localStorage.getItem(LEGACY_KEY) as string)).toEqual(customTiles)
    })

    it('ignores a default-valued legacy key — no seed, no tombstone', async () => {
        localStorage.setItem(LEGACY_KEY, JSON.stringify(DEFAULT_TILES))
        const logic = accountsOverviewTilesLogic()
        logic.mount()
        await expectLogic(logic).toMatchValues({ tiles: DEFAULT_TILES })
        expect(posthog.capture).not.toHaveBeenCalledWith(
            AccountsEvents.OverviewTilesLocalStorageRead,
            expect.anything()
        )
    })
})
