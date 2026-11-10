import { ManualLinkSourceType } from '~/types'

/**
 * The provider a bucket URL belongs to, or null when the host names none of them.
 *
 * S3-compatible stores (MinIO, Wasabi, Backblaze) are reached through the `aws` provider on hosts
 * of their own, so an unrecognized host is normal and must not be read as a wrong provider.
 */
export function storageProviderFromUrl(url: string | undefined): ManualLinkSourceType | null {
    if (!url) {
        return null
    }
    // Match on the hostname alone. A bucket path can carry another provider's domain as a folder
    // name, and matching the whole URL reads that as the provider.
    let hostname: string
    try {
        hostname = new URL(url).hostname.toLowerCase()
    } catch {
        return null
    }
    if (hostname === 'amazonaws.com' || hostname.endsWith('.amazonaws.com')) {
        return 'aws'
    }
    if (hostname === 'storage.googleapis.com' || hostname.endsWith('.storage.googleapis.com')) {
        return 'google-cloud'
    }
    // Azure blob storage answers on a different suffix per cloud (commercial, China, US government),
    // so match the `blob` service label rather than one of those suffixes.
    if (hostname.includes('.blob.')) {
        return 'azure'
    }
    if (hostname.endsWith('.r2.cloudflarestorage.com')) {
        return 'cloudflare-r2'
    }
    return null
}
