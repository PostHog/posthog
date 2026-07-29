import fs from 'fs'
import path from 'path'

import {
    type BuiltModelRow,
    DISCOUNT_REPORT_ROW_LIMIT,
    DISCOUNT_SUMMARY_ENV,
    type DiscountReportEntry,
    type EndpointCandidate,
    type RunTotals,
    accumulateModelRow,
    buildDefaultCost,
    buildModelCost,
    buildModelRow,
    confirmDiscountAgainstSiblings,
    parseDiscountRate,
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
        { description: 'clamps a negative rate to 0', discount: -0.5, expected: 0 },
        { description: 'rejects a rate of exactly 1 (division by zero)', discount: 1, expected: 0 },
        { description: 'rejects a rate above 1 (would flip the sign)', discount: 1.5, expected: 0 },
    ])('$description', ({ discount, expected }) => {
        jest.spyOn(console, 'warn').mockImplementation(() => {})
        expect(parseDiscountRate({ discount })).toBe(expected)
    })

    it('warns on a negative rate, which would otherwise look like no promotion', () => {
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
        expect(parseDiscountRate({ discount: -0.5 }, 'x/y')).toBe(0)
        expect(warn).toHaveBeenCalledWith(expect.stringContaining('x/y'))
    })

    it('stays silent when there is no rate at all', () => {
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
        parseDiscountRate({}, 'x/y')
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
        // `default` is built through this. The list payload carries no rate today,
        // so without the strip the carve-out would rest on that staying true.
        const served = { prompt: '0.0000005', completion: '0.000003', discount: 0.5 }
        expect(buildModelCost(withoutDiscount(served))!.prompt_token).toBe(0.0000005)
        expect(buildModelCost(served)!.prompt_token).toBe(0.000001)
    })
})

describe('buildDefaultCost()', () => {
    it('keeps the served price when the list payload carries a rate', () => {
        // The list payload has no rate today. This is what stops the carve-out
        // from depending on that staying true.
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
        // The azure row for gpt-5.6-luna, which OpenRouter serves at discount: 0.
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
        // The openai row for gpt-5.6-luna at discount: 0.5. The recovered list
        // price must equal the undiscounted azure sibling exactly.
        expect(buildModelCost({ prompt: '0.0000005', completion: '0.000003', discount: 0.5 })).toEqual({
            prompt_token: 0.000001,
            completion_token: 0.000006,
        })
    })

    it('applies the rate uniformly to every field, flat fees included', () => {
        // web_search is a per-call fee rather than a token rate, and OpenRouter
        // discounts it at the same ratio: 0.005 against 0.01 on the azure sibling.
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
    // Each row is a promotion OpenRouter is running today paired with the list
    // price the cost book itself held for that model before the promotion began.
    // Sourced from the alibaba -> alibaba-fp8 retag, plus the two OpenAI models
    // whose list price is independently visible on an undiscounted azure route.
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
        // A payload can arrive non-empty and still yield no usable pricing, which
        // is the same "we learned nothing" state as an empty list.
        const built = buildModelRow('openai/gpt-5.6-luna', listPricing, [
            { tag: 'openai', pricing: { prompt: 'x' } },
            {},
        ])
        expect(built!.checked).toBe(false)
        expect(Object.keys(built!.cost)).toEqual(['default'])
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
        // `default` is what provider-matching.ts resolves `$ai_provider: openrouter`
        // onto, and OpenRouter really does bill the promo rate, so it must not move.
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
            endpoints: [{ key: 'openai', discount: 0.5 }],
            confirmation: 'confirmed',
        })
    })

    it('reports no discount entry when every endpoint is at list price', () => {
        const built = buildModelRow('openai/gpt-5.6-luna', listPricing, [endpoint('azure', '0.000001')])
        expect(built!.checked).toBe(true)
        expect(built!.discount).toBeUndefined()
    })

    it('never lets an endpoint claim the `default` key', () => {
        // A route tagged "default" would otherwise overwrite the served price with
        // a de-discounted one, which is the exact over-report this branch avoids.
        const built = buildModelRow('evil/model', listPricing, [endpoint('default', '0.0000009', 0.5)])
        expect(built!.cost.default).toEqual(listCost)
        expect(built!.cost['provider-default'].prompt_token).toBe(0.0000018)
    })

    it('reports not-checkable when no undiscounted sibling exists', () => {
        // The shape of every Qwen model: Alibaba is the only route, so the
        // arithmetic cannot be independently corroborated.
        const built = buildModelRow('qwen/qwen-plus', listPricing, [endpoint('alibaba-fp8', '0.000000169', 0.35)])
        expect(built!.discount?.confirmation).toBe('not-checkable')
    })

    it('warns once, naming the model, on an out-of-range rate', () => {
        // The rate is parsed twice per endpoint; only the call carrying the model
        // context should speak, or the log gains an unattributable duplicate.
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
        // The key is interpolated into canonical-providers.ts as a string literal,
        // so an apostrophe must not be able to reach it.
        const built = buildModelRow('evil/model', listPricing, [
            { tag: '!!!', provider_name: "o'brien <script>", pricing: { prompt: '0.000001', completion: '0.000001' } },
        ])
        const key = Object.keys(built!.cost).find((k) => k !== 'default')!
        expect(key).toBe('provider-o-brien-script')
        expect(key).toMatch(/^[a-z0-9-]+$/)
    })
})

describe('confirmDiscountAgainstSiblings()', () => {
    it('is not checkable without a discounted endpoint', () => {
        expect(confirmDiscountAgainstSiblings([candidate('azure', '0.000001', 0)])).toBe('not-checkable')
    })

    it('is not checkable without an undiscounted sibling', () => {
        // Every Qwen model: Alibaba is the only first-party route.
        expect(confirmDiscountAgainstSiblings([candidate('alibaba-fp8', '0.000000169', 0.35)])).toBe('not-checkable')
    })

    it('confirms when the de-discounted price lands on an undiscounted sibling', () => {
        // gpt-5.6-luna: openai at 0.5 recovers 0.000001, exactly azure's rate.
        expect(
            confirmDiscountAgainstSiblings([candidate('openai', '0.0000005', 0.5), candidate('azure', '0.000001', 0)])
        ).toBe('confirmed')
    })

    it('reports unconfirmed when the recovered price matches no sibling', () => {
        expect(
            confirmDiscountAgainstSiblings([candidate('openai', '0.0000005', 0.5), candidate('azure', '0.000009', 0)])
        ).toBe('unconfirmed')
    })

    it('confirms on any one matching route when several are discounted', () => {
        expect(
            confirmDiscountAgainstSiblings([
                candidate('openai-flex', '0.00000025', 0.5),
                candidate('openai', '0.0000005', 0.5),
                candidate('azure', '0.000001', 0),
            ])
        ).toBe('confirmed')
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
        { description: 'strips angle brackets so markup cannot render', input: '<img src=x>', expected: 'img src=x' },
        { description: 'strips backticks so code spans cannot escape', input: 'a`b', expected: 'ab' },
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
        endpoints: [{ key: 'openai', discount: 0.5 }],
        confirmation: 'confirmed',
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
        // Three rows so the numerator and denominator differ: a ratio fixture
        // where every checkable row is confirmed reads the same under a
        // confirmed-count and a checkable-count, and proves neither.
        const report = renderDiscountReport([
            entry(),
            entry({ model: 'aaa/unconfirmed', confirmation: 'unconfirmed' }),
            entry({
                model: 'qwen/qwen-plus',
                endpoints: [
                    { key: 'alibaba-fp8', discount: 0.35 },
                    { key: 'streamlake', discount: 0.4 },
                ],
                confirmation: 'not-checkable',
            }),
        ])
        expect(report).toContain('**4 endpoint(s)**')
        expect(report).toContain('**3 model(s)**')
        expect(report).toContain('1/2 checkable')
    })

    it('puts the confirmation verdict on the row it belongs to', () => {
        const report = renderDiscountReport([entry({ confirmation: 'unconfirmed' })])
        expect(report).toContain('| unconfirmed |')
    })

    it('repeats neither model nor verdict on a continuation row', () => {
        const report = renderDiscountReport([
            entry({
                endpoints: [
                    { key: 'openai', discount: 0.5 },
                    { key: 'openai-flex', discount: 0.5 },
                ],
            }),
        ])
        const rows = report.split('\n').filter((line) => line.includes('50%'))
        expect(rows[0]).toContain('openai/gpt-5.6-luna')
        expect(rows[1]).not.toContain('openai/gpt-5.6-luna')
        expect(rows[1]).not.toContain('confirmed')
    })

    it('reports models it could not check rather than claiming a clean run', () => {
        // Absence of a measurement is not a measurement of zero: a run whose
        // endpoint calls all failed must not read as "no promotions".
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
                endpoints: Array.from({ length: endpointsEach }, (_, e) => ({ key: `k${e}`, discount: 0.5 })),
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
        // 32 endpoints is the widest model in the catalogue today, so a
        // model-based cap would render 32x the rows it promises.
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
        // The key is sanitized separately from the model id, so it needs its own
        // input or dropping one of the two calls stays green.
        const report = renderDiscountReport([entry({ endpoints: [{ key: 'a|b\n| pwned | 9 | 9 |', discount: 0.5 }] })])
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
        expect(acc.models).toEqual([{ model: 'openai/gpt-5.6-luna', cost: { default: cost('0.000001') } }])
    })

    it('collects a discount entry when the row reports one', () => {
        const discount = {
            model: 'm',
            endpoints: [{ key: 'openai', discount: 0.5 }],
            confirmation: 'confirmed' as const,
        }
        expect(accumulateModelRow(built({ discount }), 'm', totals()).discounts).toEqual([discount])
    })

    it('counts a row that could not be checked', () => {
        // This is the number the PR body reports, so the wire from `checked` to
        // the summary has to be covered, not just its two ends.
        expect(accumulateModelRow(built({ checked: false }), 'm', totals()).uncheckedModels).toBe(1)
    })

    it('accumulates across successive calls', () => {
        // Every field has to accumulate the same way, or a caller picks up one
        // that silently stayed behind.
        let acc = totals()
        acc = accumulateModelRow(built({ checked: false }), 'a', acc)
        acc = accumulateModelRow(built({ checked: false }), 'b', acc)
        expect(acc.models).toHaveLength(2)
        expect(acc.uncheckedModels).toBe(2)
    })

    it('leaves the totals it was handed untouched', () => {
        const base = totals()
        accumulateModelRow(built({ checked: false }), 'a', base)
        expect(base.models).toHaveLength(0)
        expect(base.uncheckedModels).toBe(0)
    })

    it('does not count a row that was checked', () => {
        expect(accumulateModelRow(built({ checked: true }), 'm', totals()).uncheckedModels).toBe(0)
    })
})

describe('writeOutputs()', () => {
    const summaryPath = '/tmp/does-not-matter-discount-summary.md'

    afterEach(() => {
        delete process.env[DISCOUNT_SUMMARY_ENV]
    })

    it('writes the price book before the summary', () => {
        // Ordering is the protection: the summary only decorates a PR body, so it
        // must never be the write that discards a completed run.
        process.env[DISCOUNT_SUMMARY_ENV] = summaryPath
        const writes: string[] = []
        jest.spyOn(fs, 'writeFileSync').mockImplementation(((file: string) => {
            writes.push(String(file))
        }) as never)

        writeOutputs([{ model: 'm', cost: { default: cost('0.000001')! } }], [], 0)

        const priceBook = writes.findIndex((f) => f.endsWith('llm-costs.json'))
        const summary = writes.findIndex((f) => f === summaryPath)
        // Both must actually happen; a missing price-book write would otherwise
        // satisfy a bare index comparison at -1.
        expect(priceBook).toBeGreaterThanOrEqual(0)
        expect(summary).toBeGreaterThanOrEqual(0)
        expect(priceBook).toBeLessThan(summary)
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
        const writes: string[] = []
        jest.spyOn(fs, 'writeFileSync').mockImplementation(((file: string) => {
            writes.push(String(file))
        }) as never)

        writeOutputs([{ model: 'm', cost: { default: cost('0.000001')! } }], [], 0)

        expect(writes.some((f) => f === summaryPath)).toBe(false)
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
        expect(workflow).toContain(`cat "$${DISCOUNT_SUMMARY_ENV}"`)
    })
})

describe('module import safety', () => {
    it('does not fetch or write generated files when imported', () => {
        // Without the entry guard, importing the module hits the live OpenRouter
        // API and rewrites the committed price book mid-test-run. Spies are
        // installed before the module loads here so the assertion catches that,
        // rather than the damage catching it first.
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
