export function decideResponse(featureFlags) {
    return {
        config: {
            enable_collect_everything: true,
        },
        toolbarParams: {
            toolbarVersion: 'toolbar',
            jsURL: 'http://localhost:8234/',
        },
        isAuthenticated: true,
        supportedCompression: ['gzip', 'gzip-js', 'lz64'],
        featureFlags,
        sessionRecording: {
            endpoint: '/s/',
        },
    }
}
