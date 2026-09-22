export async function listAllPages<T>(
    requestPage: (offset: number) => Promise<{ results: T[]; next?: string | null }>
): Promise<T[]> {
    const results: T[] = []
    let offset = 0

    while (true) {
        const response = await requestPage(offset)
        results.push(...response.results)

        if (!response.next || response.results.length === 0) {
            return results
        }
        offset += response.results.length
    }
}
