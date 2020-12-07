jest.mock('node-fetch', () => {
    const responsesToUrls = {
        'https://google.com/results.json?query=fetched': { count: 2, query: 'bla', results: [true, true] },
    }
    return jest.fn(
        (url) =>
            new Promise((resolve) =>
                resolve({
                    json: () => new Promise((resolve) => resolve(responsesToUrls[url]) || { fetch: 'mock' }),
                    text: () => new Promise((resolve) => resolve(JSON.stringify(responsesToUrls[url])) || 'fetchmock'),
                })
            )
    )
})
