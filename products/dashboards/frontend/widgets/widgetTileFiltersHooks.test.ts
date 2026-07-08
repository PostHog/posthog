import { act, renderHook } from '@testing-library/react'

import { WIDGET_TILE_REFRESH_DEBOUNCE_MS } from './constants'
import { useWidgetTileConfigPersist } from './widgetTileFiltersHooks'

describe('useWidgetTileConfigPersist', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('clears pending debounce when persistConfigNow runs', async () => {
        const onUpdateConfig = jest.fn().mockResolvedValue(undefined)
        const { result } = renderHook(() => useWidgetTileConfigPersist(onUpdateConfig))

        act(() => {
            result.current.persistConfigDebounced({ limit: 10, status: 'active' })
        })

        await act(async () => {
            await result.current.persistConfigNow({ limit: 10, status: 'resolved' })
        })

        act(() => {
            jest.advanceTimersByTime(WIDGET_TILE_REFRESH_DEBOUNCE_MS)
        })

        expect(onUpdateConfig).toHaveBeenCalledTimes(1)
        expect(onUpdateConfig).toHaveBeenCalledWith({ limit: 10, status: 'resolved' })
    })
})
