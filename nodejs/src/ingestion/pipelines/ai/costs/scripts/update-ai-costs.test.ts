import fs from 'fs'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import {
    type BuiltModelRow,
    DISCOUNT_REPORT_ROW_LIMIT,
    DISCOUNT_SUMMARY_ENV,
    type DiscountReportEntry,
    type EndpointCandidate,
    type RunTotals,
    UNCHECKED_WARN_FRACTION,
    accumulateModelRow,
    buildDefaultCost,
    buildModelCost,
    buildModelRow,
    collectModelRows,
    confirmDiscountAgainstSiblings,
    fetchOpenRouterCosts,
    finalizeTotals,
    foldModelIntoTotals,
    parseDiscountRate,
    readEndpointsFromOpenRouter,
    renderDiscountReport,
    sanitizeReportCell,
    withoutDiscount,
    writeOutputs,
} from './update-ai-costs'

/** Build a cost the way the fetch loop does, so tests exercise the real de-discount. */
const cost = (promptPrice: string, discount = 0, completion = promptPrice): ReturnType<typeof buildModelCost> => {
    const built = buildModelCost({ prompt: promptPrice, completion, discount })
    if (!built) {
        throw new Error(`fixture priced at ${promptPrice} failed to build`)
    }
    return built
}

const candidate = (key: string, promptPrice: string, discount: number): EndpointCandidate => ({
    key,
    cost: cost(promptPrice, discount)!,
    discount,
})

/** An endpoints-payload entry shaped the way OpenRouter serves it. */
const endpoint = (tag: string, promptPrice: string, discount = 0): Record<string, unknown> => ({
    tag,
    provider_name: tag,
    pricing: { prompt: promptPrice, completion: promptPrice, discount },
})

describe('parseDiscountRate()', () => {
    it.each<{ description: string; discount: unknown; expected: number }>([
        { description: 'returns 0 when the field is absent', discount: undefined, expected: 0 },
        { description: 'returns 0 for null', discount: null, expected: 0 },
        { description: 'returns 0 for an explicit zero', discount: 0, expected: 0 },
        { description: 'reads a fractional rate', discount: 0.35, expected: 0.35 },
        { description: 'reads a rate served as a string', discount: '0.5', expected: 0.5 },
        { description: 'reads a negative rate as a markup', discount: -0.1, expected: -0.1 },
        { description: 'rejects a rate of exactly 1 (division by zero)', discount: 1, expected: 0 },
        { description: 'rejects a rate above 1 (would flip the sign)', discount: 1.5, expected: 0 },
    ])('$description', ({ discount, expected }) => {
        jest.spyOn(console, 'warn').mockImplementation(() => {})
        expect(parseDiscountRate({ discount })).toBe(expected)
    })

    it('recovers list from a markup, which is a negative rate', () => {
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
        expect(parseDiscountRate({ discount: -0.1 }, 'x/y')).toBe(-0.1)
        expect(warn).not.toHaveBeenCalled()
        expect(buildModelCost({ prompt: '0.0000011', completion: '0.0000011', discount: -0.1 })!.prompt_token).toBe(
            0.000001
        )
    })

    it.each<{ description: string; discount: unknown }>([
        { description: 'an object', discount: {} },
        { description: 'an array', discount: ['0.5'] },
        { description: 'a boolean', discount: true },
        { description: 'an empty string', discount: '' },
        { description: 'a whitespace string', discount: '   ' },
        { description: 'an unparseable string', discount: 'abc' },
    ])('warns on a present but unusable rate: $description', ({ discount }) => {
        // Read as "no promotion", these store the promo price as list.
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
        expect(parseDiscountRate({ discount }, 'x/y')).toBe(0)
        expect(warn).toHaveBeenCalledWith(expect.stringContaining('x/y'))
    })

    it('stays silent when there is no rate at all', () => {
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
        parseDiscountRate({}, 'x/y')
        expect(warn).not.toHaveBeenCalled()
    })

    it('warns exactly once on an unparseable string rate', () => {
        // The decimal parser logs its own failure; one bad field, one line.
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
        expect(parseDiscountRate({ discount: 'abc' }, 'x/y')).toBe(0)
        expect(warn).toHaveBeenCalledTimes(1)
    })

    it('stays silent on an unparseable rate when warnings are suppressed', () => {
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
        parseDiscountRate({ discount: 'abc' }, 'x/y', false)
        expect(warn).not.toHaveBeenCalled()
    })

    it('warns naming the model when the rate is out of range', () => {
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
        parseDiscountRate({ discount: 2 }, 'openai/gpt-5.6-luna (openai)')
        expect(warn).toHaveBeenCalledWith(expect.stringContaining('openai/gpt-5.6-luna (openai)'))
    })
})

describe('withoutDiscount()', () => {
    it('returns undefined for absent pricing', () => {
        expect(withoutDiscount(undefined)).toBeUndefined()
    })

    it('drops the rate and keeps every other field', () => {
        expect(withoutDiscount({ prompt: '1', completion: '2', discount: 0.5 })).toEqual({
            prompt: '1',
            completion: '2',
        })
    })

    it('keeps a cost at the served price even when a rate is present', () => {
        // Without the strip the carve-out rests on the list payload never gaining a rate.
        const served = { prompt: '0.0000005', completion: '0.000003', discount: 0.5 }
        expect(buildModelCost(withoutDiscount(served))!.prompt_token).toBe(0.0000005)
        expect(buildModelCost(served)!.prompt_token).toBe(0.000001)
    })
})

describe('buildDefaultCost()', () => {
    it('keeps the served price when the list payload carries a rate', () => {
        expect(buildDefaultCost({ prompt: '0.0000005', completion: '0.000003', discount: 0.5 })!.prompt_token).toBe(
            0.0000005
        )
    })

    it('behaves like the plain builder when there is no rate', () => {
        expect(buildDefaultCost({ prompt: '0.000001', completion: '0.000006' })).toEqual({
            prompt_token: 0.000001,
            completion_token: 0.000006,
        })
    })
})

describe('buildModelCost() discount handling', () => {
    it('returns null when pricing is absent', () => {
        expect(buildModelCost(undefined)).toBeNull()
    })

    it('leaves an undiscounted endpoint untouched', () => {
        expect(buildModelCost({ prompt: '0.000001', completion: '0.000006', discount: 0 })).toEqual({
            prompt_token: 0.000001,
            completion_token: 0.000006,
        })
    })

    it('leaves pricing untouched when no discount field is present at all', () => {
        expect(buildModelCost({ prompt: '0.000001', completion: '0.000006' })).toEqual({
            prompt_token: 0.000001,
            completion_token: 0.000006,
        })
    })

    it('divides a promo price back up to list', () => {
        // Must land exactly on the undiscounted azure sibling.
        expect(buildModelCost({ prompt: '0.0000005', completion: '0.000003', discount: 0.5 })).toEqual({
            prompt_token: 0.000001,
            completion_token: 0.000006,
        })
    })

    it('applies the rate uniformly to every field, flat fees included', () => {
        // web_search is a per-call fee and is discounted at the same ratio.
        expect(
            buildModelCost({
                prompt: '0.0000005',
                completion: '0.000003',
                input_cache_read: '0.00000005',
                web_search: '0.005',
                discount: 0.5,
            })
        ).toEqual({
            prompt_token: 0.000001,
            completion_token: 0.000006,
            cache_read_token: 0.0000001,
            web_search: 0.01,
        })
    })

    it('does not adjust prices when the rate is out of range', () => {
        jest.spyOn(console, 'warn').mockImplementation(() => {})
        expect(buildModelCost({ prompt: '0.000001', completion: '0.000006', discount: 1 })).toEqual({
            prompt_token: 0.000001,
            completion_token: 0.000006,
        })
    })

    it('omits optional fields that are absent or zero, as before', () => {
        expect(buildModelCost({ prompt: '0.000001', completion: '0.000006', web_search: '0', discount: 0.5 })).toEqual({
            prompt_token: 0.000002,
            completion_token: 0.000012,
        })
    })
})

describe('buildModelCost() recovers prices the cost book previously recorded', () => {
    // Expectations are the list prices the cost book itself held before each
    // promotion began, so a wrong divisor fails on values this suite did not pick.
    it.each<{ model: string; served: string; discount: number; list: number }>([
        { model: 'qwen/qwen-plus prompt', served: '0.000000169', discount: 0.35, list: 0.00000026 },
        { model: 'qwen/qwen-plus completion', served: '0.000000507', discount: 0.35, list: 0.00000078 },
        { model: 'qwen/qwen3-max prompt', served: '0.000000507', discount: 0.35, list: 0.00000078 },
        { model: 'qwen/qwen3-max completion', served: '0.000002535', discount: 0.35, list: 0.0000039 },
        { model: 'qwen/qwen3-14b prompt', served: '0.000000147875', discount: 0.35, list: 0.0000002275 },
        { model: 'qwen/qwen3-235b-a22b prompt', served: '0.00000029575', discount: 0.35, list: 0.000000455 },
        { model: 'qwen/qwen3-coder-flash prompt', served: '0.00000012675', discount: 0.35, list: 0.000000195 },
        { model: 'qwen/qwen3.6-max-preview prompt', served: '0.000000832', discount: 0.2, list: 0.00000104 },
        { model: 'qwen/qwen3.5-plus-20260420 prompt', served: '0.000000225', discount: 0.25, list: 0.0000003 },
        { model: 'qwen/qwen3.6-flash prompt', served: '0.000000140625', discount: 0.25, list: 0.0000001875 },
        { model: 'openai/gpt-5.6-luna prompt', served: '0.0000005', discount: 0.5, list: 0.000001 },
        { model: 'openai/gpt-5.6-terra prompt', served: '0.00000125', discount: 0.5, list: 0.0000025 },
    ])('$model', ({ served, discount, list }) => {
        expect(cost(served, discount)!.prompt_token).toBe(list)
    })
})

describe('buildModelRow()', () => {
    const listPricing = { prompt: '0.0000005', completion: '0.0000005' }
    const listCost = cost('0.0000005')!

    it('reports nothing was checked when there are no endpoints', () => {
        const built = buildModelRow('openai/gpt-5.6-luna', listPricing, [])
        expect(built!.checked).toBe(false)
        expect(built!.discount).toBeUndefined()
        expect(built!.cost).toEqual({ default: listCost })
    })

    it('reports nothing was checked when every endpoint fails to parse', () => {
        // A non-empty payload can still yield no usable pricing.
        const built = buildModelRow('openai/gpt-5.6-luna', listPricing, [
            { tag: 'openai', pricing: { prompt: 'x' } },
            {},
        ])
        expect(built!.checked).toBe(false)
        expect(Object.keys(built!.cost)).toStrictEqual(['default'])
    })

    it('stores each endpoint at its de-discounted list price', () => {
        const built = buildModelRow('openai/gpt-5.6-luna', listPricing, [
            endpoint('openai', '0.0000005', 0.5),
            endpoint('azure', '0.000001'),
        ])
        expect(built!.checked).toBe(true)
        expect(built!.cost.openai.prompt_token).toBe(0.000001)
        expect(built!.cost.azure.prompt_token).toBe(0.000001)
    })

    it('leaves `default` exactly as OpenRouter served it', () => {
        // provider-matching.ts resolves `$ai_provider: openrouter` onto `default`,
        // and OpenRouter does bill the promo rate, so it must not move.
        const built = buildModelRow('openai/gpt-5.6-luna', listPricing, [endpoint('openai', '0.0000005', 0.5)])
        expect(built!.cost.default).toEqual(listCost)
        expect(built!.cost.default.prompt_token).toBe(0.0000005)
    })

    it('reports the discounted endpoints and the confirmation verdict', () => {
        const built = buildModelRow('openai/gpt-5.6-luna', listPricing, [
            endpoint('openai', '0.0000005', 0.5),
            endpoint('azure', '0.000001'),
        ])
        expect(built!.discount).toEqual({
            model: 'openai/gpt-5.6-luna',
            endpoints: [{ key: 'openai', discount: 0.5, confirmation: 'confirmed' as const }],
        })
    })

    it('reports no discount entry when every endpoint is at list price', () => {
        const built = buildModelRow('openai/gpt-5.6-luna', listPricing, [endpoint('azure', '0.000001')])
        expect(built!.checked).toBe(true)
        expect(built!.discount).toBeUndefined()
    })

    it('never lets an endpoint claim the `default` key', () => {
        // Otherwise it overwrites the served price with a de-discounted one.
        const built = buildModelRow('evil/model', listPricing, [endpoint('default', '0.0000009', 0.5)])
        expect(built!.cost.default).toEqual(listCost)
        expect(built!.cost['provider-default'].prompt_token).toBe(0.0000018)
    })

    it('reports not-checkable when no undiscounted sibling exists', () => {
        // Every Qwen model: Alibaba is the only route, so nothing corroborates it.
        const built = buildModelRow('qwen/qwen-plus', listPricing, [endpoint('alibaba-fp8', '0.000000169', 0.35)])
        expect(built!.discount?.endpoints[0].confirmation).toBe('not-checkable')
    })

    it('warns once, naming the model, on an out-of-range rate', () => {
        // Parsed twice per endpoint; a second warn would be unattributable.
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
        buildModelRow('openai/gpt-5.6-luna', listPricing, [endpoint('openai', '0.000001', 1.5)])
        expect(warn).toHaveBeenCalledTimes(1)
        expect(warn).toHaveBeenCalledWith(expect.stringContaining('openai/gpt-5.6-luna'))
    })

    it('returns null when the model has no usable list pricing', () => {
        expect(buildModelRow('x/y', { prompt: 'nonsense' }, [])).toBeNull()
    })

    it('keeps `default` at the served price even if the list payload gains a rate', () => {
        const built = buildModelRow('x/y', { ...listPricing, discount: 0.5 }, [endpoint('openai', '0.0000005', 0.5)])
        expect(built!.cost.default.prompt_token).toBe(0.0000005)
        expect(built!.cost.openai.prompt_token).toBe(0.000001)
    })

    it('confines a hostile provider name to a safe key', () => {
        // Interpolated into generated TypeScript, so an apostrophe must not reach it.
        const built = buildModelRow('evil/model', listPricing, [
            { tag: '!!!', provider_name: "o'brien <script>", pricing: { prompt: '0.000001', completion: '0.000001' } },
        ])
        const key = Object.keys(built!.cost).find((k) => k !== 'default')!
        expect(key).toBe('provider-o-brien-script')
        expect(key).toMatch(/^[a-z0-9-]+$/)
    })
})

describe('confirmDiscountAgainstSiblings()', () => {
    it('is not checkable for an undiscounted route', () => {
        const azure = candidate('azure', '0.000001', 0)
        expect(confirmDiscountAgainstSiblings(azure, [azure])).toBe('not-checkable')
    })

    it('is not checkable without an undiscounted sibling', () => {
        // Every Qwen model: Alibaba is the only first-party route.
        const alibaba = candidate('alibaba-fp8', '0.000000169', 0.35)
        expect(confirmDiscountAgainstSiblings(alibaba, [alibaba])).toBe('not-checkable')
    })

    it('confirms when the de-discounted price lands on an undiscounted sibling', () => {
        const openai = candidate('openai', '0.0000005', 0.5)
        expect(confirmDiscountAgainstSiblings(openai, [openai, candidate('azure', '0.000001', 0)])).toBe('confirmed')
    })

    it('reports unconfirmed when the recovered price matches no sibling', () => {
        const openai = candidate('openai', '0.0000005', 0.5)
        expect(confirmDiscountAgainstSiblings(openai, [openai, candidate('azure', '0.000009', 0)])).toBe('unconfirmed')
    })

    it('judges each promoted route on its own', () => {
        const flex = candidate('openai-flex', '0.00000025', 0.5)
        const openai = candidate('openai', '0.0000005', 0.5)
        const all = [flex, openai, candidate('azure', '0.000001', 0)]
        expect(confirmDiscountAgainstSiblings(openai, all)).toBe('confirmed')
        expect(confirmDiscountAgainstSiblings(flex, all)).toBe('unconfirmed')
    })

    it('compares on the prompt price, not the completion price', () => {
        // Every other fixture sets completion equal to prompt.
        const discounted: EndpointCandidate = {
            key: 'openai',
            cost: buildModelCost({ prompt: '0.0000005', completion: '0.000009', discount: 0.5 })!,
            discount: 0.5,
        }
        const sibling: EndpointCandidate = {
            key: 'azure',
            cost: buildModelCost({ prompt: '0.000001', completion: '0.000002' })!,
            discount: 0,
        }
        expect(confirmDiscountAgainstSiblings(discounted, [discounted, sibling])).toBe('confirmed')
    })
})

describe('sanitizeReportCell()', () => {
    it.each<{ description: string; input: string; expected: string }>([
        {
            description: 'passes an ordinary model id through',
            input: 'openai/gpt-5.6-luna',
            expected: 'openai/gpt-5.6-luna',
        },
        { description: 'folds newlines so a row cannot be split', input: 'a\nb\r\nc', expected: 'a b c' },
        { description: 'strips pipes so a row cannot gain columns', input: 'a|b', expected: 'ab' },
        {
            description: 'strips angle brackets and everything else outside the allowlist',
            input: '<img src=x>',
            expected: 'img srcx',
        },
        { description: 'strips backticks so code spans cannot escape', input: 'a`b', expected: 'ab' },
        {
            description: 'strips image syntax so a remote image cannot load in the PR body',
            input: '![pricing](https://example.com/pixel)',
            expected: 'pricinghttps://example.com/pixel',
        },
        {
            description: 'strips link syntax so no clickable target survives',
            input: '[click](https://evil.example)',
            expected: 'clickhttps://evil.example',
        },
    ])('$description', ({ input, expected }) => {
        expect(sanitizeReportCell(input)).toBe(expected)
    })

    it('bounds the cell length', () => {
        expect(sanitizeReportCell('x'.repeat(500))).toHaveLength(120)
    })
})

describe('renderDiscountReport()', () => {
    const entry = (over: Partial<DiscountReportEntry> = {}): DiscountReportEntry => ({
        model: 'openai/gpt-5.6-luna',
        endpoints: [{ key: 'openai', discount: 0.5, confirmation: 'confirmed' as const }],
        ...over,
    })

    it('says so plainly when nothing is discounted', () => {
        expect(renderDiscountReport([])).toContain('No discounted endpoints found')
    })

    it('names each discounted model, endpoint and rate', () => {
        const report = renderDiscountReport([entry()])
        expect(report).toContain('openai/gpt-5.6-luna')
        expect(report).toContain('`openai`')
        expect(report).toContain('50%')
    })

    it('counts endpoints and models, and reports the confirmed ratio', () => {
        // Numerator and denominator must differ, or a checkable-count reads the same.
        const report = renderDiscountReport([
            entry(),
            entry({
                model: 'aaa/unconfirmed',
                endpoints: [{ key: 'openai', discount: 0.5, confirmation: 'unconfirmed' as const }],
            }),
            entry({
                model: 'qwen/qwen-plus',
                endpoints: [
                    { key: 'alibaba-fp8', discount: 0.35, confirmation: 'not-checkable' as const },
                    { key: 'streamlake', discount: 0.4, confirmation: 'not-checkable' as const },
                ],
            }),
        ])
        expect(report).toContain('**4 endpoint(s)**')
        expect(report).toContain('**3 model(s)**')
        expect(report).toContain('1/2 checkable')
    })

    it('puts the confirmation verdict on the row it belongs to', () => {
        const report = renderDiscountReport([
            entry({ endpoints: [{ key: 'openai', discount: 0.5, confirmation: 'unconfirmed' as const }] }),
        ])
        expect(report).toContain('| unconfirmed |')
    })

    it('blanks the model on a continuation row and keeps that route verdict', () => {
        const report = renderDiscountReport([
            entry({
                endpoints: [
                    { key: 'openai', discount: 0.5, confirmation: 'confirmed' as const },
                    { key: 'openai-flex', discount: 0.5, confirmation: 'confirmed' as const },
                ],
            }),
        ])
        const rows = report.split('\n').filter((line) => line.includes('50%'))
        expect(rows[0]).toContain('openai/gpt-5.6-luna')
        expect(rows[1]).not.toContain('openai/gpt-5.6-luna')
        expect(rows[1]).toContain('confirmed')
    })

    it('reports models it could not check rather than claiming a clean run', () => {
        // A run whose endpoint calls all failed must not read as "no promotions".
        expect(renderDiscountReport([], 17)).toContain('17 model(s) could not be checked')
        expect(renderDiscountReport([entry()], 17)).toContain('17 model(s) could not be checked')
    })

    it('says nothing about unchecked models when every model was checked', () => {
        expect(renderDiscountReport([entry()], 0)).not.toContain('could not be checked')
    })

    const manyEntries = (count: number, endpointsEach = 1): DiscountReportEntry[] =>
        Array.from({ length: count }, (_, index) =>
            entry({
                model: `vendor/model-${String(index).padStart(4, '0')}`,
                endpoints: Array.from({ length: endpointsEach }, (_, e) => ({
                    key: `k${e}`,
                    discount: 0.5,
                    confirmation: 'confirmed' as const,
                })),
            })
        )

    it('pins the row limit to a literal, so the cap cannot drift with the code', () => {
        expect(DISCOUNT_REPORT_ROW_LIMIT).toBe(200)
    })

    it('lists everything and says nothing about omissions at exactly the limit', () => {
        const report = renderDiscountReport(manyEntries(DISCOUNT_REPORT_ROW_LIMIT))
        expect(report.split('\n').filter((line) => line.includes('50%'))).toHaveLength(DISCOUNT_REPORT_ROW_LIMIT)
        expect(report).not.toContain('more discounted model(s)')
    })

    it('omits exactly one model at one over the limit', () => {
        const report = renderDiscountReport(manyEntries(DISCOUNT_REPORT_ROW_LIMIT + 1))
        expect(report).toContain('and 1 more discounted model(s) not listed')
    })

    it('caps on rendered rows, not models, since a model can carry many endpoints', () => {
        // The widest model carries 32 endpoints, so a model cap under-counts rows.
        const report = renderDiscountReport(manyEntries(20, 32))
        expect(report.split('\n').filter((line) => line.includes('50%')).length).toBeLessThanOrEqual(
            DISCOUNT_REPORT_ROW_LIMIT
        )
        expect(report).toContain('more discounted model(s) not listed')
    })

    it('escapes a hostile model id so it cannot break the table', () => {
        const report = renderDiscountReport([entry({ model: 'evil/x|y\n| pwned | 1 | 2 |' })])
        expect(report).not.toContain('pwned | 1 | 2 |')
        expect(report.split('\n').filter((line) => line.includes('50%'))).toHaveLength(1)
    })

    it('escapes a hostile endpoint key so it cannot break the table', () => {
        // Sanitized separately from the model id, so it needs its own input.
        const report = renderDiscountReport([
            entry({
                endpoints: [{ key: 'a|b\n| pwned | 9 | 9 |', discount: 0.5, confirmation: 'confirmed' as const }],
            }),
        ])
        expect(report).not.toContain('pwned | 9 | 9 |')
        expect(report.split('\n').filter((line) => line.includes('50%'))).toHaveLength(1)
    })

    it('sorts models so the report is stable across runs', () => {
        const report = renderDiscountReport([entry({ model: 'zzz/model' }), entry({ model: 'aaa/model' })])
        expect(report.indexOf('aaa/model')).toBeLessThan(report.indexOf('zzz/model'))
    })
})

describe('accumulateModelRow()', () => {
    const totals = (): RunTotals => ({ models: [], discounts: [], uncheckedModels: 0 })
    const built = (over: Partial<BuiltModelRow> = {}): BuiltModelRow => ({
        cost: { default: cost('0.000001')! },
        checked: true,
        ...over,
    })

    it('collects the row into the price book', () => {
        const acc = accumulateModelRow(built(), 'openai/gpt-5.6-luna', totals())
        expect(acc.models).toStrictEqual([{ model: 'openai/gpt-5.6-luna', cost: { default: cost('0.000001') } }])
    })

    it('collects a discount entry when the row reports one', () => {
        const discount = {
            model: 'm',
            endpoints: [{ key: 'openai', discount: 0.5, confirmation: 'confirmed' as const }],
        }
        expect(accumulateModelRow(built({ discount }), 'm', totals()).discounts).toStrictEqual([discount])
    })

    it('counts a row that could not be checked', () => {
        // The wire from `checked` to the summary, not just its two ends.
        expect(accumulateModelRow(built({ checked: false }), 'm', totals()).uncheckedModels).toBe(1)
    })

    it('accumulates across successive calls', () => {
        // Every field must accumulate the same way, or one silently stays behind.
        let acc = totals()
        acc = accumulateModelRow(built({ checked: false }), 'a', acc)
        acc = accumulateModelRow(built({ checked: false }), 'b', acc)
        expect(acc.models).toHaveLength(2)
        expect(acc.uncheckedModels).toBe(2)
    })

    it('leaves the totals it was handed untouched', () => {
        const base = totals()
        const discount: DiscountReportEntry = {
            model: 'a',
            endpoints: [{ key: 'openai', discount: 0.5, confirmation: 'confirmed' }],
        }
        accumulateModelRow(built({ checked: false, discount }), 'a', base)
        expect(base.models).toHaveLength(0)
        expect(base.discounts).toHaveLength(0)
        expect(base.uncheckedModels).toBe(0)
    })

    it('does not count a row that was checked', () => {
        expect(accumulateModelRow(built({ checked: true }), 'm', totals()).uncheckedModels).toBe(0)
    })
})

describe('foldModelIntoTotals()', () => {
    const listPricing = { prompt: '0.0000005', completion: '0.0000005' }
    const start = (): RunTotals => ({ models: [], discounts: [], uncheckedModels: 0 })

    it('folds a priced model into the totals', () => {
        const out = foldModelIntoTotals('a/b', listPricing, [], start())
        expect(out.models).toHaveLength(1)
        expect(out.uncheckedModels).toBe(1)
    })

    it('skips a model whose list pricing will not parse', () => {
        // Without the skip the price book gains a row whose default is null.
        jest.spyOn(console, 'warn').mockImplementation(() => {})
        const out = foldModelIntoTotals('a/b', { prompt: 'nonsense' }, [], start())
        expect(out.models).toHaveLength(0)
    })

    it('leaves the totals it was handed untouched', () => {
        const base = start()
        foldModelIntoTotals('a/b', listPricing, [], base)
        expect(base.models).toHaveLength(0)
        expect(base.uncheckedModels).toBe(0)
    })

    it('keeps what was already collected when it skips', () => {
        // From empty, "added nothing" and "discarded everything" look the same.
        jest.spyOn(console, 'warn').mockImplementation(() => {})
        const seeded = foldModelIntoTotals('good/one', listPricing, [endpoint('openai', '0.000001', 0.5)], start())
        expect(seeded.models).toHaveLength(1)
        const after = foldModelIntoTotals('bad/one', { prompt: 'nonsense' }, [], seeded)
        expect(after.models).toHaveLength(1)
        expect(after.discounts).toHaveLength(1)
        expect(after.uncheckedModels).toBe(seeded.uncheckedModels)
    })

    it('files the row and the discount under the model id it was given', () => {
        const out = foldModelIntoTotals('a/b', listPricing, [endpoint('openai', '0.000001', 0.5)], start())
        expect(out.models[0].model).toBe('a/b')
        expect(out.discounts[0].model).toBe('a/b')
    })

    it('warns naming the model it skipped', () => {
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
        foldModelIntoTotals('a/b', undefined, [], start())
        expect(warn).toHaveBeenCalledWith(expect.stringContaining('Skipping'), 'a/b')
    })
})

describe('finalizeTotals()', () => {
    const row = (model: string) => ({ model, cost: { default: cost('0.000001')! } })

    it('orders models by id so output does not follow response order', () => {
        const out = finalizeTotals({ models: [row('z/z'), row('a/a')], discounts: [], uncheckedModels: 0 })
        expect(out.models.map((m) => m.model)).toStrictEqual(['a/a', 'z/z'])
    })

    it('leaves the totals it was handed untouched', () => {
        // Same contract accumulateModelRow carries.
        const base: RunTotals = { models: [row('z/z'), row('a/a')], discounts: [], uncheckedModels: 0 }
        finalizeTotals(base)
        expect(base.models.map((m) => m.model)).toStrictEqual(['z/z', 'a/a'])
    })

    it('carries the other totals through unchanged', () => {
        const out = finalizeTotals({ models: [], discounts: [], uncheckedModels: 4 })
        expect(out.uncheckedModels).toBe(4)
    })
})

describe('collectModelRows()', () => {
    const priced = (id: string) => ({ id, pricing: { prompt: '0.0000005', completion: '0.0000005' } })
    const noEndpoints = (): Promise<unknown[]> => Promise.resolve([])

    it('orders the price book by model id', () => {
        // Response order rewrites the whole file each run and opens a PR on noise.
        return collectModelRows([priced('z/z'), priced('a/a')], noEndpoints).then((totals) => {
            expect(totals.models.map((m) => m.model)).toStrictEqual(['a/a', 'z/z'])
        })
    })

    it('skips an entry with no id and keeps going', async () => {
        jest.spyOn(console, 'warn').mockImplementation(() => {})
        const totals = await collectModelRows([{}, priced('a/a')], noEndpoints)
        expect(totals.models).toHaveLength(1)
        expect(totals.models.map((m) => m.model)).toStrictEqual(['a/a'])
    })

    it('skips an entry with no id even when its pricing is valid', async () => {
        // An id-less entry with parseable pricing is the only input that tells the
        // id guard apart from the pricing guard below it.
        jest.spyOn(console, 'warn').mockImplementation(() => {})
        const totals = await collectModelRows(
            [{ pricing: { prompt: '0.000001', completion: '0.000001' } }, priced('a/a')],
            noEndpoints
        )
        expect(totals.models.map((m) => m.model)).toStrictEqual(['a/a'])
    })

    it('reports the unchecked count with its denominator', async () => {
        // Assert the whole phrase: the per-model progress line also carries an
        // "n/m" and would satisfy a bare substring check.
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
        jest.spyOn(console, 'log').mockImplementation(() => {})
        await collectModelRows([priced('a/a'), priced('b/b')], noEndpoints)
        expect(warn).toHaveBeenCalledWith(expect.stringContaining('2/2 model(s) had no usable endpoint pricing'))
    })

    it('warns rather than logs once too much of the catalogue is unchecked', async () => {
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
        jest.spyOn(console, 'log').mockImplementation(() => {})
        await collectModelRows([priced('a/a')], noEndpoints)
        expect(warn).toHaveBeenCalledWith(expect.stringContaining('degraded'))
    })

    it('stays at log level when the unchecked share is within the steady state', async () => {
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
        const log = jest.spyOn(console, 'log').mockImplementation(() => {})
        // One unchecked model in a catalogue large enough to stay under the share.
        const models = [priced('a/a'), ...Array.from({ length: 20 }, (_, i) => priced(`m/${i}`))]
        await collectModelRows(models, (id) => Promise.resolve(id === 'a/a' ? [] : [endpoint('openai', '0.000001')]))
        expect(warn).not.toHaveBeenCalledWith(expect.stringContaining('degraded'))
        expect(log).toHaveBeenCalledWith(expect.stringContaining('1/21 model(s) had no usable endpoint pricing'))
    })

    it('pins the unchecked warn share to a literal', () => {
        expect(UNCHECKED_WARN_FRACTION).toBe(0.1)
    })

    it('counts models whose endpoints came back empty', async () => {
        const totals = await collectModelRows([priced('a/a'), priced('b/b')], noEndpoints)
        expect(totals.uncheckedModels).toBe(2)
    })

    it('collects discounts from the endpoints it is handed', async () => {
        const totals = await collectModelRows([priced('a/a')], () =>
            Promise.resolve([endpoint('openai', '0.0000005', 0.5), endpoint('azure', '0.000001')])
        )
        expect(totals.discounts).toHaveLength(1)
        expect(totals.discounts[0].endpoints[0].confirmation).toBe('confirmed')
        expect(totals.models[0].cost.openai.prompt_token).toBe(0.000001)
    })

    it('reads endpoints once per model, by id', async () => {
        const seen: string[] = []
        await collectModelRows([priced('a/a'), priced('b/b')], (id) => {
            seen.push(id)
            return Promise.resolve([])
        })
        expect(seen).toStrictEqual(['a/a', 'b/b'])
    })
})

describe('readEndpointsFromOpenRouter()', () => {
    const mockFetch = (impl: () => unknown): jest.SpyInstance =>
        jest.spyOn(global, 'fetch' as never).mockImplementation(impl as never)

    it('returns the endpoints the payload carries', async () => {
        mockFetch(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ data: { endpoints: [1, 2] } }) }))
        await expect(readEndpointsFromOpenRouter('a/b')).resolves.toStrictEqual([1, 2])
    })

    it('degrades to no endpoints on a non-ok response, and says so', async () => {
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
        mockFetch(() => Promise.resolve({ ok: false, status: 429, statusText: 'Too Many Requests' }))
        await expect(readEndpointsFromOpenRouter('a/b')).resolves.toStrictEqual([])
        expect(warn).toHaveBeenCalledWith(expect.stringContaining('a/b'))
    })

    it('degrades to no endpoints when the request throws, and says so', async () => {
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
        mockFetch(() => Promise.reject(new Error('socket hang up')))
        await expect(readEndpointsFromOpenRouter('a/b')).resolves.toStrictEqual([])
        expect(warn).toHaveBeenCalledWith(expect.stringContaining('Error fetching'), 'a/b', expect.anything())
    })

    it('degrades to no endpoints when the payload has no endpoints key', async () => {
        mockFetch(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }))
        await expect(readEndpointsFromOpenRouter('a/b')).resolves.toStrictEqual([])
    })

    it('encodes each path segment of the model id', async () => {
        let requested = ''
        mockFetch(((url: string) => {
            requested = url
            return Promise.resolve({ ok: true, json: () => Promise.resolve({ data: { endpoints: [] } }) })
        }) as never)
        await readEndpointsFromOpenRouter('anthropic/claude-sonnet-5:batch')
        expect(requested).toContain('anthropic/claude-sonnet-5%3Abatch')
    })
})

describe('fetchOpenRouterCosts()', () => {
    const listPayload = {
        data: [{ id: 'a/b', pricing: { prompt: '0.0000005', completion: '0.0000005' } }],
    }
    const endpointsPayload = { data: { endpoints: [endpoint('openai', '0.0000005', 0.5)] } }

    const mockFetch = (): jest.SpyInstance =>
        jest.spyOn(global, 'fetch' as never).mockImplementation(((url: string) =>
            Promise.resolve({
                ok: true,
                json: () => Promise.resolve(url.includes('/endpoints') ? endpointsPayload : listPayload),
            })) as never)

    it('reads per-endpoint pricing, not just the list payload', async () => {
        // Pins that production hands the loop the real reader, not a fake.
        jest.spyOn(console, 'log').mockImplementation(() => {})
        mockFetch()
        const totals = await fetchOpenRouterCosts()
        expect(totals.models[0].cost.openai.prompt_token).toBe(0.000001)
        expect(totals.uncheckedModels).toBe(0)
    })

    it('reads the models out of the payload envelope', async () => {
        jest.spyOn(console, 'log').mockImplementation(() => {})
        mockFetch()
        const totals = await fetchOpenRouterCosts()
        expect(totals.models.map((m) => m.model)).toStrictEqual(['a/b'])
    })

    it('throws when the models list cannot be fetched', async () => {
        jest.spyOn(global, 'fetch' as never).mockImplementation((() =>
            Promise.resolve({ ok: false, status: 503, statusText: 'Service Unavailable' })) as never)
        await expect(fetchOpenRouterCosts()).rejects.toThrow('Failed to fetch OpenRouter models')
    })

    it('throws when the models list is not JSON', async () => {
        jest.spyOn(global, 'fetch' as never).mockImplementation((() =>
            Promise.resolve({ ok: true, json: () => Promise.reject(new Error('bad json')) })) as never)
        await expect(fetchOpenRouterCosts()).rejects.toThrow('Failed to parse OpenRouter API response')
    })
})

describe('writeOutputs()', () => {
    const summaryPath = '/tmp/does-not-matter-discount-summary.md'

    afterEach(() => {
        delete process.env[DISCOUNT_SUMMARY_ENV]
    })

    /** Record both halves of every write, so content is pinned and not just the path. */
    const captureWrites = (): Array<[string, string]> => {
        const writes: Array<[string, string]> = []
        jest.spyOn(fs, 'writeFileSync').mockImplementation(((file: string, body: string) => {
            writes.push([String(file), String(body)])
        }) as never)
        return writes
    }

    it('writes the price book before the summary', () => {
        // Ordering is the protection: the summary only decorates a PR body, so it
        // must never be the write that discards a completed run.
        process.env[DISCOUNT_SUMMARY_ENV] = summaryPath
        const writes = captureWrites()

        writeOutputs([{ model: 'm', cost: { default: cost('0.000001')! } }], [], 0)

        const priceBook = writes.findIndex(([f]) => f.endsWith('llm-costs.json'))
        const summary = writes.findIndex(([f]) => f === summaryPath)
        // Both must actually happen; a missing price-book write would otherwise
        // satisfy a bare index comparison at -1.
        expect(priceBook).toBeGreaterThanOrEqual(0)
        expect(summary).toBeGreaterThanOrEqual(0)
        expect(priceBook).toBeLessThan(summary)
    })

    it('writes the rows it was handed into the price book', () => {
        process.env[DISCOUNT_SUMMARY_ENV] = summaryPath
        const writes = captureWrites()
        const rows = [{ model: 'm', cost: { default: cost('0.000001')! } }]

        writeOutputs(rows, [], 0)

        const [, body] = writes.find(([f]) => f.endsWith('llm-costs.json'))!
        expect(parseJSON(body)).toEqual(rows)
    })

    it('carries the unchecked count into the summary it writes', () => {
        // The count is produced five hops upstream; this is the hop that hands it
        // to the report, and without it the body reads as a verified clean run.
        process.env[DISCOUNT_SUMMARY_ENV] = summaryPath
        const writes = captureWrites()

        writeOutputs([{ model: 'm', cost: { default: cost('0.000001')! } }], [], 17)

        const [, body] = writes.find(([f]) => f === summaryPath)!
        expect(body).toContain('17 model(s) could not be checked')
    })

    it('renders the promotions it was handed into the summary', () => {
        // Every other call passes an empty list, which pins nothing.
        process.env[DISCOUNT_SUMMARY_ENV] = summaryPath
        const writes = captureWrites()
        const promo: DiscountReportEntry = {
            model: 'openai/gpt-5.6-luna',
            endpoints: [{ key: 'openai', discount: 0.5, confirmation: 'confirmed' }],
        }

        writeOutputs([{ model: 'm', cost: { default: cost('0.000001')! } }], [promo], 0)

        const [, body] = writes.find(([f]) => f === summaryPath)!
        expect(body).toContain('openai/gpt-5.6-luna')
        expect(body).not.toContain('No discounted endpoints found')
    })

    it('generates the provider union alongside the price book', () => {
        process.env[DISCOUNT_SUMMARY_ENV] = summaryPath
        const writes = captureWrites()

        writeOutputs([{ model: 'm', cost: { default: cost('0.000001')! } }], [], 0)

        expect(writes.some(([f]) => f.endsWith('canonical-providers.ts'))).toBe(true)
    })

    it('does not throw when the summary write fails', () => {
        process.env[DISCOUNT_SUMMARY_ENV] = summaryPath
        jest.spyOn(console, 'warn').mockImplementation(() => {})
        jest.spyOn(fs, 'writeFileSync').mockImplementation(((file: string) => {
            if (String(file) === summaryPath) {
                throw new Error('scratch disk full')
            }
        }) as never)

        expect(() => writeOutputs([{ model: 'm', cost: { default: cost('0.000001')! } }], [], 0)).not.toThrow()
    })

    it('writes no summary when the env var is unset', () => {
        const writes = captureWrites()

        writeOutputs([{ model: 'm', cost: { default: cost('0.000001')! } }], [], 0)

        expect(writes.some(([f]) => f === summaryPath)).toBe(false)
    })
})

describe('workflow contract', () => {
    it('sets the same env var the script reads', () => {
        // Two hand-maintained strings in different languages. Nothing else binds
        // them, and a rename drops the promotions section from the PR body.
        const workflow = fs.readFileSync(
            path.join(__dirname, '../../../../../../../.github/workflows/update-ai-costs.yml'),
            'utf8'
        )
        expect(workflow).toContain(`${DISCOUNT_SUMMARY_ENV}=`) // the step that sets it
        // The exact guard and the exact read, so renaming either one fails here.
        expect(workflow).toContain(`[ -f "$${DISCOUNT_SUMMARY_ENV}" ]`)
        expect(workflow).toContain(`cat "$${DISCOUNT_SUMMARY_ENV}" >> "$body_file"`)
        // The sink: the assembled body must be what reaches GitHub on both paths.
        expect(workflow.match(/--body-file "\$body_file"/g) ?? []).toHaveLength(2)
    })
})

describe('module import safety', () => {
    it('does not fetch or write generated files when imported', () => {
        // Without the guard, importing hits the live API and rewrites the committed
        // price book. Spies go in before the module loads so the assertion catches it.
        const fetchSpy = jest
            .spyOn(global, 'fetch' as never)
            .mockImplementation((() =>
                Promise.resolve({ ok: true, json: () => Promise.resolve({ data: [] }) })) as never)
        const writeSpy = jest.spyOn(fs, 'writeFileSync').mockImplementation(() => {})
        const mkdirSpy = jest.spyOn(fs, 'mkdirSync').mockImplementation(() => undefined)

        jest.isolateModules(() => {
            require('./update-ai-costs')
        })

        expect(fetchSpy).not.toHaveBeenCalled()
        expect(writeSpy).not.toHaveBeenCalled()
        expect(mkdirSpy).not.toHaveBeenCalled()
    })
})
