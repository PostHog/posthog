import { filteredFetch, raiseIfUserProvidedUrlUnsafe } from '../../src/utils/fetch'

const { FetchError } = filteredFetch

test('raiseIfUserProvidedUrlUnsafe', async () => {
    // Sync test cases with posthog/api/test/test_utils.py
    await raiseIfUserProvidedUrlUnsafe('https://google.com?q=20') // Safe
    await raiseIfUserProvidedUrlUnsafe('https://posthog.com') // Safe
    await raiseIfUserProvidedUrlUnsafe('https://posthog.com/foo/bar') // Safe, with path
    await raiseIfUserProvidedUrlUnsafe('https://posthog.com:443') // Safe, good port
    await raiseIfUserProvidedUrlUnsafe('https://1.1.1.1') // Safe, public IP
    await expect(() => raiseIfUserProvidedUrlUnsafe('https://posthog.com:80')).rejects.toBeInstanceOf(FetchError) // Bad port
    await expect(raiseIfUserProvidedUrlUnsafe('ftp://posthog.com')).rejects.toBeInstanceOf(FetchError) // Bad scheme
    await expect(raiseIfUserProvidedUrlUnsafe('')).rejects.toBeInstanceOf(FetchError) // Empty
    await expect(raiseIfUserProvidedUrlUnsafe('@@@')).rejects.toBeInstanceOf(FetchError) // Invalid format
    await expect(raiseIfUserProvidedUrlUnsafe('posthog.com')).rejects.toBeInstanceOf(FetchError) // No scheme
    await expect(raiseIfUserProvidedUrlUnsafe('http://localhost')).rejects.toBeInstanceOf(FetchError) // Internal
    await expect(raiseIfUserProvidedUrlUnsafe('http://192.168.0.5')).rejects.toBeInstanceOf(FetchError) // Internal
    await expect(raiseIfUserProvidedUrlUnsafe('http://0.0.0.0')).rejects.toBeInstanceOf(FetchError) // Internal
    await expect(raiseIfUserProvidedUrlUnsafe('http://10.0.0.24')).rejects.toBeInstanceOf(FetchError) // Internal
    await expect(raiseIfUserProvidedUrlUnsafe('http://172.20.0.21')).rejects.toBeInstanceOf(FetchError) // Internal
    await expect(raiseIfUserProvidedUrlUnsafe('http://fgtggggzzggggfd.com')).rejects.toBeInstanceOf(FetchError) // Non-existent
})
