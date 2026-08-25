const mockAgentConstructor = jest.fn().mockImplementation(() => ({}))
const mockProxyAgentConstructor = jest.fn().mockImplementation(() => ({}))

jest.mock('undici', () => ({
    ...jest.requireActual('undici'),
    Agent: mockAgentConstructor,
    ProxyAgent: mockProxyAgentConstructor,
}))

describe('secure request dispatchers', () => {
    it('uses one HTTP/2 connection per origin through the configured proxy', () => {
        const savedProxyEnvironment = {
            HTTPS_PROXY: process.env.HTTPS_PROXY,
            HTTP_PROXY: process.env.HTTP_PROXY,
            https_proxy: process.env.https_proxy,
            http_proxy: process.env.http_proxy,
        }
        process.env.HTTPS_PROXY = 'http://smokescreen:4750'
        delete process.env.HTTP_PROXY
        delete process.env.https_proxy
        delete process.env.http_proxy

        try {
            jest.isolateModules(() => {
                require('./request')
            })
        } finally {
            for (const [name, value] of Object.entries(savedProxyEnvironment)) {
                if (value === undefined) {
                    delete process.env[name]
                } else {
                    process.env[name] = value
                }
            }
        }

        expect(mockAgentConstructor).not.toHaveBeenCalledWith(expect.objectContaining({ allowH2: true }))
        expect(mockProxyAgentConstructor).toHaveBeenCalledWith(
            expect.objectContaining({
                uri: 'http://smokescreen:4750',
                allowH2: true,
                connections: 1,
                maxConcurrentStreams: 6,
                requestTls: { allowH2: true },
            })
        )
    })
})
