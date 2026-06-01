import { act, renderHook, waitFor } from '@testing-library/react'

import {
    __clearTaxonomicResourceCache,
    invalidateTaxonomicResource,
    invalidateTaxonomicResourcesWhere,
    peekTaxonomicResource,
    useTaxonomicResource,
} from './useTaxonomicResource'

describe('useTaxonomicResource', () => {
    beforeEach(() => {
        __clearTaxonomicResourceCache()
    })

    it('runs the query function and exposes data', async () => {
        const fn = jest.fn().mockResolvedValue({ results: ['a', 'b'] })
        const { result } = renderHook(() => useTaxonomicResource(['k', 1], fn))

        expect(result.current.isLoading).toBe(true)
        expect(result.current.data).toBeUndefined()

        await waitFor(() => expect(result.current.data).toEqual({ results: ['a', 'b'] }))
        expect(result.current.isLoading).toBe(false)
        expect(result.current.isFetching).toBe(false)
        expect(fn).toHaveBeenCalledTimes(1)
    })

    it('returns cached data within staleTime without refetching', async () => {
        const fn = jest.fn().mockResolvedValue('first')
        const { result, unmount } = renderHook(() => useTaxonomicResource(['cached'], fn, { staleTime: 60_000 }))
        await waitFor(() => expect(result.current.data).toBe('first'))
        unmount()

        const fn2 = jest.fn().mockResolvedValue('second')
        const r2 = renderHook(() => useTaxonomicResource(['cached'], fn2, { staleTime: 60_000 }))
        // Should be served from cache, no new fetch.
        expect(r2.result.current.data).toBe('first')
        expect(fn2).not.toHaveBeenCalled()
    })

    it('refetches after staleTime elapses', async () => {
        const fn = jest.fn().mockResolvedValueOnce('v1').mockResolvedValueOnce('v2')
        // staleTime 0 means always stale → always refetch on mount.
        const { result, unmount } = renderHook(() => useTaxonomicResource(['stale'], fn, { staleTime: 0 }))
        await waitFor(() => expect(result.current.data).toBe('v1'))
        expect(fn).toHaveBeenCalledTimes(1)
        unmount()

        const r2 = renderHook(() => useTaxonomicResource(['stale'], fn, { staleTime: 0 }))
        await waitFor(() => expect(r2.result.current.data).toBe('v2'))
        expect(fn).toHaveBeenCalledTimes(2)
    })

    it('skips execution when enabled=false', () => {
        const fn = jest.fn().mockResolvedValue('x')
        const { result } = renderHook(() => useTaxonomicResource(['gated'], fn, { enabled: false }))
        expect(fn).not.toHaveBeenCalled()
        expect(result.current.isLoading).toBe(false)
        expect(result.current.data).toBeUndefined()
    })

    it('keepPreviousData returns prior data while a new key is loading', async () => {
        let resolveSecond: (v: string) => void = () => {}
        const fn = jest
            .fn()
            .mockResolvedValueOnce('a')
            .mockImplementationOnce(() => new Promise<string>((r) => (resolveSecond = r)))

        const { result, rerender } = renderHook(
            ({ id }: { id: number }) => useTaxonomicResource(['kpd', id], fn, { keepPreviousData: true }),
            { initialProps: { id: 1 } }
        )
        await waitFor(() => expect(result.current.data).toBe('a'))

        rerender({ id: 2 })
        // Second key still loading, previous data should be visible.
        expect(result.current.data).toBe('a')
        expect(result.current.isFetching).toBe(true)

        await act(async () => {
            resolveSecond('b')
            await Promise.resolve()
        })
        await waitFor(() => expect(result.current.data).toBe('b'))
    })

    it('without keepPreviousData, data is undefined while new key loads', async () => {
        let resolveSecond: (v: string) => void = () => {}
        const fn = jest
            .fn()
            .mockResolvedValueOnce('a')
            .mockImplementationOnce(() => new Promise<string>((r) => (resolveSecond = r)))

        const { result, rerender } = renderHook(
            ({ id }: { id: number }) => useTaxonomicResource(['nkpd', id], fn, { keepPreviousData: false }),
            { initialProps: { id: 1 } }
        )
        await waitFor(() => expect(result.current.data).toBe('a'))

        rerender({ id: 2 })
        expect(result.current.data).toBeUndefined()
        expect(result.current.isLoading).toBe(true)

        await act(async () => {
            resolveSecond('b')
            await Promise.resolve()
        })
        await waitFor(() => expect(result.current.data).toBe('b'))
    })

    it('dedupes concurrent identical requests', async () => {
        const fn = jest.fn().mockImplementation(() => new Promise((r) => setTimeout(() => r('once'), 10)))
        const a = renderHook(() => useTaxonomicResource(['dedup'], fn))
        const b = renderHook(() => useTaxonomicResource(['dedup'], fn))
        await waitFor(() => expect(a.result.current.data).toBe('once'))
        expect(b.result.current.data).toBe('once')
        expect(fn).toHaveBeenCalledTimes(1)
    })

    it('exposes errors and stops loading', async () => {
        const fn = jest.fn().mockRejectedValue(new Error('boom'))
        const { result } = renderHook(() => useTaxonomicResource(['err'], fn))
        await waitFor(() => expect(result.current.error).toBeInstanceOf(Error))
        expect((result.current.error as Error).message).toBe('boom')
        expect(result.current.isLoading).toBe(false)
        expect(result.current.data).toBeUndefined()
    })

    it('refetch() bypasses staleTime and updates data', async () => {
        const fn = jest.fn().mockResolvedValueOnce('first').mockResolvedValueOnce('second')
        const { result } = renderHook(() => useTaxonomicResource(['refetch'], fn, { staleTime: 60_000 }))
        await waitFor(() => expect(result.current.data).toBe('first'))

        await act(async () => {
            await result.current.refetch()
        })
        await waitFor(() => expect(result.current.data).toBe('second'))
        expect(fn).toHaveBeenCalledTimes(2)
    })

    it('aborts in-flight request when last subscriber unmounts', async () => {
        const seenSignals: AbortSignal[] = []
        const fn = jest.fn().mockImplementation(({ signal }: { signal: AbortSignal }) => {
            seenSignals.push(signal)
            return new Promise(() => {})
        })
        const { unmount } = renderHook(() => useTaxonomicResource(['abort'], fn))
        expect(seenSignals).toHaveLength(1)
        expect(seenSignals[0].aborted).toBe(false)
        unmount()
        expect(seenSignals[0].aborted).toBe(true)
    })

    it('does not poison the cache key when an in-flight request is aborted', async () => {
        // First call rejects with an AbortError when its signal aborts;
        // second call (after re-mount) resolves normally.
        const fn = jest
            .fn()
            .mockImplementationOnce(
                ({ signal }: { signal: AbortSignal }) =>
                    new Promise<string>((_resolve, reject) => {
                        signal.addEventListener('abort', () =>
                            reject(new DOMException('The operation was aborted.', 'AbortError'))
                        )
                    })
            )
            .mockResolvedValueOnce('second')

        // Mount, then unmount before the request settles → aborts it.
        const { unmount } = renderHook(() => useTaxonomicResource(['poison'], fn))
        unmount()
        // Let the abort rejection settle.
        await act(async () => {
            await Promise.resolve()
        })

        // Re-mounting the same key must re-fetch — the aborted request must
        // not have stored an error that halts auto-fetch forever.
        const r2 = renderHook(() => useTaxonomicResource(['poison'], fn))
        await waitFor(() => expect(r2.result.current.data).toBe('second'))
        expect(r2.result.current.error).toBeUndefined()
        expect(fn).toHaveBeenCalledTimes(2)
    })

    it('passes a fresh AbortSignal that is not aborted while a subscriber is mounted', async () => {
        const seen: AbortSignal[] = []
        const fn = jest.fn().mockImplementation(({ signal }: { signal: AbortSignal }) => {
            seen.push(signal)
            return Promise.resolve('ok')
        })
        const { result } = renderHook(() => useTaxonomicResource(['signal'], fn))
        await waitFor(() => expect(result.current.data).toBe('ok'))
        expect(seen[0].aborted).toBe(false)
    })

    it('hashes the key as JSON so identical content shares the cache slot', async () => {
        const fn = jest.fn().mockResolvedValue('shared')
        const r1 = renderHook(() => useTaxonomicResource(['hash', { a: 1, b: 2 }], fn))
        const r2 = renderHook(() => useTaxonomicResource(['hash', { a: 1, b: 2 }], fn))
        await waitFor(() => expect(r1.result.current.data).toBe('shared'))
        expect(r2.result.current.data).toBe('shared')
        expect(fn).toHaveBeenCalledTimes(1)
    })

    it('invalidateTaxonomicResource() forces refetch on next read', async () => {
        const fn = jest.fn().mockResolvedValueOnce('x').mockResolvedValueOnce('y')
        const { result, rerender } = renderHook(() => useTaxonomicResource(['inv'], fn, { staleTime: 60_000 }))
        await waitFor(() => expect(result.current.data).toBe('x'))
        invalidateTaxonomicResource(['inv'])
        rerender()
        await waitFor(() => expect(result.current.data).toBe('y'))
        expect(fn).toHaveBeenCalledTimes(2)
    })

    it('invalidateTaxonomicResourcesWhere() invalidates every key matching the predicate', async () => {
        const fnA = jest.fn().mockResolvedValueOnce('a1').mockResolvedValueOnce('a2')
        const fnB = jest.fn().mockResolvedValueOnce('b1').mockResolvedValueOnce('b2')
        const fnC = jest.fn().mockResolvedValueOnce('c1')

        const ra = renderHook(() => useTaxonomicResource(['taxonomic-list', 'cohorts', 'k1'], fnA))
        const rb = renderHook(() => useTaxonomicResource(['taxonomic-list', 'cohorts', 'k2'], fnB))
        const rc = renderHook(() => useTaxonomicResource(['taxonomic-list', 'events', 'k3'], fnC))

        await waitFor(() => expect(ra.result.current.data).toBe('a1'))
        await waitFor(() => expect(rb.result.current.data).toBe('b1'))
        await waitFor(() => expect(rc.result.current.data).toBe('c1'))

        // Invalidate only the cohort entries — events stays cached.
        invalidateTaxonomicResourcesWhere((key) => key[0] === 'taxonomic-list' && key[1] === 'cohorts')

        ra.rerender()
        rb.rerender()
        rc.rerender()

        await waitFor(() => expect(ra.result.current.data).toBe('a2'))
        await waitFor(() => expect(rb.result.current.data).toBe('b2'))
        expect(fnA).toHaveBeenCalledTimes(2)
        expect(fnB).toHaveBeenCalledTimes(2)
        expect(fnC).toHaveBeenCalledTimes(1)
    })

    it('peekTaxonomicResource() returns current cached value', async () => {
        const fn = jest.fn().mockResolvedValue({ items: [1, 2] })
        const { result } = renderHook(() => useTaxonomicResource(['peek'], fn))
        await waitFor(() => expect(result.current.data).toEqual({ items: [1, 2] }))
        expect(peekTaxonomicResource(['peek'])).toEqual({ items: [1, 2] })
        expect(peekTaxonomicResource(['peek', 'missing'])).toBeUndefined()
    })

    it('survives changing fn identity without re-fetching when data is fresh', async () => {
        const fn1 = jest.fn().mockResolvedValue('once')
        const fn2 = jest.fn().mockResolvedValue('twice')
        const { result, rerender } = renderHook(
            ({ f }: { f: jest.Mock }) => useTaxonomicResource(['fnid'], f, { staleTime: 60_000 }),
            { initialProps: { f: fn1 } }
        )
        await waitFor(() => expect(result.current.data).toBe('once'))
        rerender({ f: fn2 })
        // Fresh data, fn identity change must not trigger a new fetch.
        expect(fn2).not.toHaveBeenCalled()
        expect(result.current.data).toBe('once')
    })
})
