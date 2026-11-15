import type { BreakPointFunction } from 'kea'

export async function loadOfflineRequest<T>(request: () => Promise<T>, breakpoint: BreakPointFunction): Promise<T> {
    try {
        const result = await request()
        breakpoint()
        return result
    } catch (error) {
        breakpoint()
        throw error
    }
}
