import { describeStorageProviderMismatch } from './storageProvider'

describe('describeStorageProviderMismatch', () => {
    it.each([
        {
            provider: 'google-cloud',
            url: 'https://your-org.s3.amazonaws.com/invoices/*.pqt',
            urlLabel: 'S3',
            chosenLabel: 'Google Cloud Storage',
        },
        {
            provider: 'aws',
            url: 'https://storage.googleapis.com/your-org/invoices/*.pqt',
            urlLabel: 'Google Cloud Storage',
            chosenLabel: 'S3',
        },
        {
            provider: 'aws',
            url: 'https://your-account-id.r2.cloudflarestorage.com/invoices/*.pqt',
            urlLabel: 'Cloudflare R2',
            chosenLabel: 'S3',
        },
        {
            provider: 'cloudflare-r2',
            url: 'https://yourstorageaccount.blob.core.windows.net/your-container/*.pqt',
            urlLabel: 'Azure',
            chosenLabel: 'Cloudflare R2',
        },
    ] as const)(
        'names both providers for a $urlLabel URL under $chosenLabel',
        ({ provider, url, urlLabel, chosenLabel }) => {
            const message = describeStorageProviderMismatch(url, provider)

            expect(message).toContain(`points at ${urlLabel}`)
            expect(message).toContain(`you chose ${chosenLabel}`)
        }
    )

    // An S3-compatible store reached through the `aws` provider lives on a host of its own, so an
    // unrecognized host must stay silent rather than accuse the user of picking the wrong provider.
    it.each([
        { provider: 'aws', url: 'https://your-org.s3.amazonaws.com/invoices/*.pqt', case: 'a matching host' },
        {
            provider: 'google-cloud',
            url: 'https://storage.googleapis.com/your-org/invoices/*.pqt',
            case: 'a matching host',
        },
        {
            provider: 'aws',
            url: 'https://s3.us-west-1.wasabisys.com/your-org/invoices/*.pqt',
            case: 'an S3-compatible host',
        },
        { provider: 'aws', url: '', case: 'an empty URL' },
        { provider: 'aws', url: undefined, case: 'no URL yet' },
        {
            provider: 'google-cloud',
            url: 'https://storage.googleapis.com/your-org/amazonaws.com/*.pqt',
            case: "another provider's domain used as a folder name",
        },
        { provider: 'aws', url: 'not a url', case: 'an unparsable URL' },
    ] as const)('stays quiet for $case', ({ provider, url }) => {
        expect(describeStorageProviderMismatch(url, provider)).toBeNull()
    })
})
