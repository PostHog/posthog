export const waitForExpect = async (fn: () => Promise<void>, timeout = 5000, interval = 50): Promise<void> => {
    // Allows for running expectations that are expected to pass eventually.
    // This is useful for, e.g. waiting for events to have been ingested into
    // the database.

    const start = Date.now()
    while (true) {
        try {
            await fn()
            return
        } catch (error) {
            if (Date.now() - start > timeout) {
                throw error
            }
            await new Promise((resolve) => setTimeout(resolve, interval))
        }
    }
}
