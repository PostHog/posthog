import { storageProviderFromUrl } from './storageProvider'

describe('storageProviderFromUrl', () => {
    it.each([
        { url: 'https://your-org.s3.amazonaws.com/invoices/*.pqt', expected: 'aws' },
        { url: 'https://storage.googleapis.com/your-org/invoices/*.pqt', expected: 'google-cloud' },
        { url: 'https://your-account-id.r2.cloudflarestorage.com/invoices/*.pqt', expected: 'cloudflare-r2' },
        { url: 'https://yourstorageaccount.blob.core.windows.net/your-container/*.pqt', expected: 'azure' },
        // Matching on the whole URL would read the folder name as the provider.
        { url: 'https://storage.googleapis.com/your-org/amazonaws.com/*.pqt', expected: 'google-cloud' },
        // An S3-compatible store reached through the `aws` provider lives on a host of its own.
        { url: 'https://s3.us-west-1.wasabisys.com/your-org/invoices/*.pqt', expected: null },
        { url: '', expected: null },
        { url: undefined, expected: null },
        { url: 'not a url', expected: null },
    ] as const)('reads $expected from $url', ({ url, expected }) => {
        expect(storageProviderFromUrl(url)).toEqual(expected)
    })
})
