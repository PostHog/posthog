export const waitForExpect = async <T>(fn: () => T | Promise<T>, timeout = 10_000, interval = 100): Promise<T> => {
    // Allows for running expectations that are expected to pass eventually.
    // This is useful for, e.g. waiting for events to have been ingested into
    // the database.

    const start = Date.now()
    while (true) {
        try {
            return await fn()
        } catch (error) {
            if (Date.now() - start > timeout) {
                throw error
            }
            await new Promise((resolve) => setTimeout(resolve, interval))
        }
    }
}
