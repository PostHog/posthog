import { resetContext } from 'kea'

import { disposablesPlugin } from '~/kea-disposables'

import { RegexMatchingRequest, RegexMatchingResult, startRegexMatching } from './regexMatching'
import { regexMatchingLogic } from './regexMatchingLogic'

jest.mock('./regexMatching', () => ({ ...jest.requireActual('./regexMatching'), startRegexMatching: jest.fn() }))

describe('regexMatchingLogic', () => {
    const checks = [{ pattern: 'a', subject: 'a' }]
    let requests: (RegexMatchingRequest & { resolve: (result: RegexMatchingResult) => void })[]
    beforeEach(() => {
        resetContext({ plugins: [disposablesPlugin] })
        requests = []
        jest.mocked(startRegexMatching).mockImplementation(() => {
            let resolve!: (result: RegexMatchingResult) => void
            const promise = new Promise<RegexMatchingResult>((done) => {
                resolve = done
            })
            const request = { promise, resolve, cancel: jest.fn() }
            requests.push(request)
            return request
        })
    })
    afterEach(() => {
        jest.clearAllMocks()
    })

    it('clears stale results on configuration changes and ignores replaced responses', async () => {
        const logic = regexMatchingLogic({ instanceKey: 'one', checks })
        const unmount = logic.mount()
        expect(logic.values.preview.status).toBe('pending')
        regexMatchingLogic({ instanceKey: 'one', checks: [{ pattern: 'b', subject: 'a' }] })
        expect(requests[0].cancel).toHaveBeenCalledTimes(1)
        requests[0].resolve({ status: 'success', results: [{ matches: true }] })
        await Promise.resolve()
        expect(logic.values.preview.status).toBe('pending')
        requests[1].resolve({ status: 'success', results: [{ matches: false }] })
        await Promise.resolve()
        expect(logic.values.preview).toEqual({ status: 'success', results: [{ matches: false }] })
        regexMatchingLogic({ instanceKey: 'one', checks: [{ pattern: 'c', subject: 'a' }] })
        expect(logic.values.preview).toEqual({ status: 'pending' })
        unmount()
    })

    it('does not retry equal props or settled work on visibility changes', async () => {
        const logic = regexMatchingLogic({ instanceKey: 'equal', checks })
        const unmount = logic.mount()
        requests[0].resolve({ status: 'error', error: 'timeout' })
        await Promise.resolve()
        regexMatchingLogic({ instanceKey: 'equal', checks: [{ pattern: 'a', subject: 'a' }] })
        document.dispatchEvent(new Event('visibilitychange'))
        expect(requests).toHaveLength(1)
        expect(logic.values.preview).toEqual({ status: 'error', error: 'timeout' })
        expect(logic.cache.disposables.registry.size).toBe(0)
        unmount()
    })

    it('keeps mounted instances independent and cancels on unmount', async () => {
        const first = regexMatchingLogic({ instanceKey: 'first', checks })
        const second = regexMatchingLogic({ instanceKey: 'second', checks })
        const unmountFirst = first.mount()
        const unmountSecond = second.mount()
        unmountFirst()
        expect(requests[0].cancel).toHaveBeenCalledTimes(1)
        expect(requests[1].cancel).not.toHaveBeenCalled()
        requests[0].resolve({ status: 'success', results: [{ matches: true }] })
        await Promise.resolve()
        expect(second.values.preview.status).toBe('pending')
        requests[1].resolve({ status: 'success', results: [{ matches: false }] })
        await Promise.resolve()
        expect(second.values.preview).toEqual({ status: 'success', results: [{ matches: false }] })
        unmountSecond()
    })

    it('does not let a previous mount dispose or dispatch into a new mount', async () => {
        const logic = regexMatchingLogic({ instanceKey: 'remount', checks })
        logic.mount()()
        const unmount = logic.mount()
        requests[0].resolve({ status: 'success', results: [{ matches: true }] })
        await Promise.resolve()
        expect(requests[1].cancel).not.toHaveBeenCalled()
        expect(logic.values.preview.status).toBe('pending')
        requests[1].resolve({ status: 'success', results: [{ matches: false }] })
        await Promise.resolve()
        expect(logic.values.preview).toEqual({ status: 'success', results: [{ matches: false }] })
        unmount()
    })

    it('stays idle for no checks and cancels when input is cleared', () => {
        const logic = regexMatchingLogic({ instanceKey: 'empty', checks: [] })
        const unmount = logic.mount()
        expect(requests).toHaveLength(0)
        expect(logic.values.preview).toEqual({ status: 'idle' })
        regexMatchingLogic({ instanceKey: 'empty', checks })
        expect(requests).toHaveLength(1)
        regexMatchingLogic({ instanceKey: 'empty', checks: [] })
        expect(requests[0].cancel).toHaveBeenCalledTimes(1)
        expect(logic.values.preview).toEqual({ status: 'idle' })
        unmount()
    })
})
