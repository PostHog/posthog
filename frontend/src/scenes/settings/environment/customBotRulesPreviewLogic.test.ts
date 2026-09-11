import { resetContext } from 'kea'

import { RegexMatchingResult, startRegexMatching } from 'lib/regex/regexMatching'

import { disposablesPlugin } from '~/kea-disposables'
import { CustomBotField, CustomBotMatcher, CustomBotRule } from '~/queries/schema/schema-general'
import { FilterLogicalOperator } from '~/types'

import { customBotRulesPreviewLogic } from './customBotRulesPreviewLogic'

jest.mock('lib/regex/regexMatching', () => ({ startRegexMatching: jest.fn() }))

describe('customBotRulesPreviewLogic', () => {
    const rule: CustomBotRule = {
        id: 'bot',
        name: 'Crawler',
        combiner: FilterLogicalOperator.And,
        items: [
            {
                id: 'ua',
                key: CustomBotField.RawUserAgent,
                matcher: CustomBotMatcher.Regex,
                pattern: '(?ii)(?s)crawler.bot',
            },
            { id: 'ip', key: CustomBotField.IP, matcher: CustomBotMatcher.Cidr, pattern: '192.0.2.0/24' },
        ],
    }
    const props = {
        instanceKey: 'test',
        rules: [rule],
        testValues: { [CustomBotField.RawUserAgent]: 'CRAWLER\nBOT', [CustomBotField.IP]: '192.0.2.5' },
    }
    let requests: { resolve: (result: RegexMatchingResult) => void; cancel: jest.Mock }[]
    const settle = async (): Promise<void> => {
        await Promise.resolve()
        await Promise.resolve()
    }

    beforeEach(() => {
        resetContext({ plugins: [disposablesPlugin] })
        requests = []
        jest.mocked(startRegexMatching)
            .mockReset()
            .mockImplementation(() => {
                let resolve!: (result: RegexMatchingResult) => void
                const promise = new Promise<RegexMatchingResult>((done) => {
                    resolve = done
                })
                const request = { resolve, cancel: jest.fn() }
                requests.push(request)
                return { promise, cancel: request.cancel }
            })
    })

    it('batches translated native regex checks and combines them with range results', async () => {
        const logic = customBotRulesPreviewLogic(props)
        const unmount = logic.mount()
        expect(logic.values.preview).toEqual({ status: 'pending' })
        expect(startRegexMatching).toHaveBeenCalledWith([
            { pattern: 'crawler.bot', flags: 'is', subject: 'CRAWLER\nBOT' },
        ])
        requests[0].resolve({ status: 'success', results: [{ matches: true }] })
        await settle()
        expect(logic.values.preview).toEqual({ status: 'success', matched: [rule] })
        customBotRulesPreviewLogic({ ...props, testValues: { ...props.testValues, [CustomBotField.IP]: '192.0.3.1' } })
        requests[1].resolve({ status: 'success', results: [{ matches: true }] })
        await settle()
        expect(logic.values.preview).toEqual({ status: 'success', matched: [] })
        unmount()
    })

    it('cancels changed input, ignores stale responses, and clears unused input', async () => {
        const logic = customBotRulesPreviewLogic(props)
        const unmount = logic.mount()
        customBotRulesPreviewLogic({ ...props, testValues: { [CustomBotField.RawUserAgent]: 'other' } })
        expect(requests[0].cancel).toHaveBeenCalledTimes(1)
        requests[0].resolve({ status: 'success', results: [{ matches: true }] })
        await settle()
        expect(logic.values.preview.status).toBe('pending')
        customBotRulesPreviewLogic({ ...props, rules: [] })
        expect(requests[1].cancel).toHaveBeenCalledTimes(1)
        expect(logic.values.preview).toEqual({ status: 'idle' })
        unmount()
    })

    it.each([
        [FilterLogicalOperator.And, false, 0],
        [FilterLogicalOperator.Or, false, 1],
        [FilterLogicalOperator.And, true, 1],
    ])('combines ordered regex results with %s and second match %s', async (combiner, secondMatch, count) => {
        const combined = {
            ...rule,
            combiner,
            items: [rule.items[0], { ...rule.items[0], id: 'second', pattern: '^crawler' }],
        }
        const logic = customBotRulesPreviewLogic({ ...props, rules: [combined] })
        const unmount = logic.mount()
        requests[0].resolve({ status: 'success', results: [{ matches: true }, { matches: secondMatch }] })
        await settle()
        expect(logic.values.preview).toEqual({ status: 'success', matched: count ? [combined] : [] })
        unmount()
    })

    it.each(['timeout', 'startup_timeout', 'unavailable', 'worker_error', 'hidden'] as const)(
        'reports %s and does not retry equal props',
        async (error) => {
            const logic = customBotRulesPreviewLogic(props)
            const unmount = logic.mount()
            requests[0].resolve({ status: 'error', error })
            await settle()
            customBotRulesPreviewLogic({ ...props, rules: [...props.rules] })
            document.dispatchEvent(new Event('visibilitychange'))
            expect(logic.values.preview).toEqual({ status: 'error', error })
            expect(requests).toHaveLength(1)
            expect(logic.cache.disposables.registry.size).toBe(0)
            unmount()
        }
    )

    it('keeps non-regex and empty previews worker-free and isolates remounted requests', async () => {
        const literalLogic = customBotRulesPreviewLogic({
            ...props,
            instanceKey: 'literal',
            rules: [{ ...rule, items: [rule.items[1]] }],
        })
        const unmountLiteral = literalLogic.mount()
        await settle()
        expect(literalLogic.values.preview).toEqual({
            status: 'success',
            matched: [{ ...rule, items: [rule.items[1]] }],
        })
        unmountLiteral()
        expect(requests).toHaveLength(0)
        const logic = customBotRulesPreviewLogic(props)
        const unmount = logic.mount()
        await settle()
        expect(logic.values.preview.status).toBe('pending')
        unmount()
        expect(requests[0].cancel).toHaveBeenCalledTimes(1)
        const unmountAgain = logic.mount()
        requests[0].resolve({ status: 'success', results: [{ matches: true }] })
        await settle()
        expect(logic.values.preview.status).toBe('pending')
        expect(requests[1].cancel).not.toHaveBeenCalled()
        unmountAgain()
    })

    it('ignores a completion after the Kea context is replaced', async () => {
        const logic = customBotRulesPreviewLogic(props)
        const unmount = logic.mount()
        resetContext({ plugins: [disposablesPlugin] })
        const replacement = customBotRulesPreviewLogic(props)
        const unmountReplacement = replacement.mount()
        requests[0].resolve({ status: 'success', results: [{ matches: true }] })
        await settle()
        expect(replacement.values.preview).toEqual({ status: 'pending' })
        requests[1].resolve({ status: 'success', results: [{ matches: false }] })
        await settle()
        expect(replacement.values.preview).toEqual({ status: 'success', matched: [] })
        unmountReplacement()
        unmount()
    })
})
