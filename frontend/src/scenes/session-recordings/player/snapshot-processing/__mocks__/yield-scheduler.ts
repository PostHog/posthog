// Mock implementation of yield-scheduler for testing
export async function yieldToMain(): Promise<void> {
    // In tests, don't actually yield - just return immediately
    return Promise.resolve()
}
