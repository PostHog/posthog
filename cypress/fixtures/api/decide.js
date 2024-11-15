export function decideResponse(featureFlags) {
    return {
        config: {
            enable_collect_everything: true,
        },
        toolbarParams: {
            toolbarVersion: 'toolbar',
        },
        isAuthenticated: true,
        supportedCompression: ['gzip', 'gzip-js', 'lz64'],
        featureFlags,
        sessionRecording: {
            endpoint: '/s/',
        },
    }
}
