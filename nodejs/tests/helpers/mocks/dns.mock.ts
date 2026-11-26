import dns from 'node:dns'

export type LookupAnswer = (options: dns.LookupOptions, callback: (...args: unknown[]) => void) => void

export const lookupAnswers = (answeredHost: string, answer: LookupAnswer): void => {
    const lookup = dns.lookup as (...args: unknown[]) => void
    jest.spyOn(dns, 'lookup').mockImplementation(((host: string, ...rest: unknown[]) => {
        if (host !== answeredHost) {
            return lookup(host, ...rest)
        }
        const callback = rest[rest.length - 1] as (...args: unknown[]) => void
        const options = (typeof rest[0] === 'object' ? rest[0] : {}) as dns.LookupOptions
        process.nextTick(() => answer(options, callback))
    }) as typeof dns.lookup)
}

export const stopAnsweringLookups = (): void => {
    if (jest.isMockFunction(dns.lookup)) {
        jest.mocked(dns.lookup).mockRestore()
    }
}

export const loopbackAddresses =
    (...addresses: string[]): LookupAnswer =>
    (options, callback) =>
        options.all
            ? callback(
                  null,
                  addresses.map((address) => ({ address, family: 4 }))
              )
            : callback(null, addresses[0], 4)

export const firstLookupGoesWhereNothingListens = (): LookupAnswer => {
    let lookups = 0
    return (options, callback) => loopbackAddresses(lookups++ === 0 ? '127.0.0.2' : '127.0.0.1')(options, callback)
}
