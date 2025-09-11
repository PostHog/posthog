/** duplicated from the plugin-server
 *  Allows for running expectations that are expected to pass eventually.
 *  This is useful for, e.g. waiting for events to have been ingested into
 *  the database.
 */
export const waitForExpect = async <T>(fn: () => T | Promise<T>, timeout = 10_000, interval = 1_000): Promise<T> => {
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
