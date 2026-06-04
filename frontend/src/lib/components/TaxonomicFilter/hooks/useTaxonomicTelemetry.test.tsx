import { act, cleanup, renderHook } from '@testing-library/react'
import posthog from 'posthog-js'

import { TaxonomicFilterGroupType } from '../types'
import { useTaxonomicTelemetry } from './useTaxonomicTelemetry'

jest.mock('posthog-js', () => ({
    __esModule: true,
    default: { capture: jest.fn() },
}))

const capture = posthog.capture as jest.Mock

const render = (
    initialQuery = ''
): ReturnType<typeof renderHook<ReturnType<typeof useTaxonomicTelemetry>, { q: string }>> =>
    renderHook(({ q }) => useTaxonomicTelemetry({ activeGroupType: TaxonomicFilterGroupType.Events, searchQuery: q }), {
        initialProps: { q: initialQuery },
    })

describe('useTaxonomicTelemetry', () => {
    beforeEach(() => {
        capture.mockClear()
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.runOnlyPendingTimers()
        jest.useRealTimers()
        cleanup()
    })

    describe('taxonomic filter closed', () => {
        it('does not fire on unmount when the user never interacted', () => {
            const { unmount } = render()
            act(() => unmount())
            expect(capture).not.toHaveBeenCalledWith('taxonomic filter closed', expect.anything())
        })

        it('fires on unmount once the user interacted, with dwell + no selection', () => {
            const { result, unmount } = render()
            act(() => result.current.markInteraction())
            act(() => unmount())
            expect(capture).toHaveBeenCalledWith(
                'taxonomic filter closed',
                expect.objectContaining({
                    groupType: TaxonomicFilterGroupType.Events,
                    hadSelection: false,
                    dwellMs: expect.any(Number),
                })
            )
        })

        it('reports hadSelection=true when an item was selected', () => {
            const { result, unmount } = render()
            act(() =>
                result.current.captureItemSelected({
                    groupType: TaxonomicFilterGroupType.Events,
                    sourceGroupType: TaxonomicFilterGroupType.Events,
                    wasFromRecents: false,
                    wasFromPinnedList: false,
                    wasQuickFilter: false,
                    hadSearchInput: false,
                })
            )
            act(() => unmount())
            expect(capture).toHaveBeenCalledWith(
                'taxonomic filter closed',
                expect.objectContaining({ hadSelection: true })
            )
        })
    })

    describe('taxonomic_filter_search_query', () => {
        it('fires debounced for a non-empty query, marked as typed', () => {
            const { rerender } = render('')
            act(() => rerender({ q: 'pageview' }))
            expect(capture).not.toHaveBeenCalledWith('taxonomic_filter_search_query', expect.anything())
            act(() => jest.advanceTimersByTime(500))
            expect(capture).toHaveBeenCalledWith('taxonomic_filter_search_query', {
                searchQuery: 'pageview',
                groupType: TaxonomicFilterGroupType.Events,
                inputMode: 'typed',
                pastedFraction: 0,
            })
        })

        it('does not fire for an empty / whitespace query', () => {
            const { rerender } = render('')
            act(() => rerender({ q: '   ' }))
            act(() => jest.advanceTimersByTime(500))
            expect(capture).not.toHaveBeenCalledWith('taxonomic_filter_search_query', expect.anything())
        })

        it.each([
            { pasted: 8, query: 'pageview', mode: 'pasted', fraction: 1 },
            { pasted: 4, query: 'pageview', mode: 'mixed', fraction: 0.5 },
        ])('classifies pasted input as $mode', ({ pasted, query, mode, fraction }) => {
            const { result, rerender } = render('')
            act(() => result.current.recordPaste(pasted))
            act(() => rerender({ q: query }))
            act(() => jest.advanceTimersByTime(500))
            expect(capture).toHaveBeenCalledWith(
                'taxonomic_filter_search_query',
                expect.objectContaining({ inputMode: mode, pastedFraction: fraction })
            )
        })

        it('resets the pasted-char accumulator after each capture', () => {
            const { result, rerender } = render('')
            act(() => result.current.recordPaste(8))
            act(() => rerender({ q: 'pageview' }))
            act(() => jest.advanceTimersByTime(500))
            capture.mockClear()
            act(() => rerender({ q: 'pageviews' }))
            act(() => jest.advanceTimersByTime(500))
            expect(capture).toHaveBeenCalledWith(
                'taxonomic_filter_search_query',
                expect.objectContaining({ inputMode: 'typed' })
            )
        })
    })

    describe('taxonomic filter item selected', () => {
        it('fires with the full payload', () => {
            const { result } = render('pa')
            act(() =>
                result.current.captureItemSelected({
                    groupType: TaxonomicFilterGroupType.SuggestedFilters,
                    sourceGroupType: TaxonomicFilterGroupType.EventProperties,
                    wasFromRecents: true,
                    wasFromPinnedList: false,
                    wasQuickFilter: false,
                    hadSearchInput: true,
                    position: 2,
                    query: 'pa',
                })
            )
            expect(capture).toHaveBeenCalledWith('taxonomic filter item selected', {
                groupType: TaxonomicFilterGroupType.SuggestedFilters,
                sourceGroupType: TaxonomicFilterGroupType.EventProperties,
                wasFromRecents: true,
                wasFromPinnedList: false,
                wasQuickFilter: false,
                hadSearchInput: true,
                position: 2,
                query: 'pa',
            })
        })

        it('spreads quick-filter props and normalises an empty query to undefined', () => {
            const { result } = render('')
            act(() =>
                result.current.captureItemSelected({
                    groupType: TaxonomicFilterGroupType.Events,
                    sourceGroupType: TaxonomicFilterGroupType.Events,
                    wasFromRecents: false,
                    wasFromPinnedList: false,
                    wasQuickFilter: true,
                    hadSearchInput: false,
                    query: '',
                    quickFilterProps: { filterName: 'click', operator: 'exact' },
                })
            )
            expect(capture).toHaveBeenCalledWith(
                'taxonomic filter item selected',
                expect.objectContaining({
                    wasQuickFilter: true,
                    filterName: 'click',
                    operator: 'exact',
                    query: undefined,
                })
            )
        })
    })
})
