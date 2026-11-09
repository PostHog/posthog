import {
    CopyObjectCommand,
    GetObjectCommand,
    HeadObjectCommand,
    HeadObjectCommandOutput,
    NoSuchKey,
    NotFound,
    PutObjectCommand,
    S3Client,
    S3ClientConfig,
} from '@aws-sdk/client-s3'
import { defaultProvider } from '@aws-sdk/credential-provider-node'
import { getSignedUrl } from '@aws-sdk/s3-request-presigner'
import { Counter } from 'prom-client'

import { CdpConfig } from '~/cdp/config'
import { EmailAttachmentMetadata } from '~/cdp/schema/cyclotron'

import { holdUntilSettled } from './in-flight-registry'

const DAY_MS = 24 * 60 * 60 * 1000
// The bucket's one lifecycle rule deletes an object this long after its creation. A self-copy resets the creation.
export const ATTACHMENT_LIFETIME_MS = 37 * DAY_MS
const UPLOAD_URL_LIFETIME_MS = 15 * 60 * 1000
// A presigned URL stops working when the credentials that signed it expire, so they must outlive the URL.
const SIGNING_CREDENTIALS_MIN_LIFETIME_MS = 16 * 60 * 1000
// The S3 client refreshes cached credentials 5 minutes before they expire.
const S3_CLIENT_REFRESH_WINDOW_MS = 5 * 60 * 1000
const PRESENT_MIN_REMAINING_MS = UPLOAD_URL_LIFETIME_MS + DAY_MS
const SHA256_HEX = /^[0-9a-f]{64}$/

export type Sha256Hex = string
export type UploadRequest = { sha256: Sha256Hex; size: number }
export type UploadSlot =
    | { sha256: Sha256Hex; status: 'present'; expiresAt: Date }
    | {
          sha256: Sha256Hex
          status: 'upload'
          url: string
          method: 'PUT'
          headers: Record<string, string>
          urlExpiresAt: Date
      }
export type AttachmentRef = Omit<EmailAttachmentMetadata, 'sizeBytes'>
export type AcceptedForSend = { files: EmailAttachmentMetadata[] }
export type RefusedForSend = { refusal: 'attachment_not_uploaded'; sha256: Sha256Hex }
export type LoadedAttachment = { file: EmailAttachmentMetadata; bytes: Uint8Array }

export class AttachmentStoreUnavailableError extends Error {
    constructor(cause: unknown) {
        super(
            `The attachment store did not answer: ${cause instanceof Error ? `${cause.name}: ${cause.message}` : cause}`,
            {
                cause,
            }
        )
        this.name = 'AttachmentStoreUnavailableError'
    }
}

export class AttachmentMissingError extends Error {
    constructor(readonly sha256: Sha256Hex) {
        super(`The attachment ${sha256} is no longer stored`)
        this.name = 'AttachmentMissingError'
    }
}

export interface AttachmentStore {
    prepareUploads(teamId: number, files: UploadRequest[]): Promise<UploadSlot[]>
    acceptForSend(teamId: number, refs: AttachmentRef[], needsUntil: Date): Promise<AcceptedForSend | RefusedForSend>
    extend(teamId: number, sha256s: Sha256Hex[], needsUntil: Date): Promise<void>
    load(teamId: number, files: EmailAttachmentMetadata[], signal: AbortSignal): Promise<LoadedAttachment[]>
}

const attachmentStoreFiles = new Counter({
    name: 'cdp_email_attachment_store_files_total',
    help: 'Files the email attachment store handled, by operation (prepare, accept, extend, load) and outcome (present, upload, kept, copied, missing, loaded).',
    labelNames: ['operation', 'outcome'],
})

type S3AttachmentStoreConfig = { bucket: string; prefix: string; timeoutMs: number }

export class S3AttachmentStore implements AttachmentStore {
    constructor(
        readonly s3: S3Client,
        private readonly signer: S3Client,
        private readonly config: S3AttachmentStoreConfig,
        private readonly now: () => Date = () => new Date()
    ) {}

    async prepareUploads(teamId: number, files: UploadRequest[]): Promise<UploadSlot[]> {
        return await Promise.all(files.map((file) => this.prepareUpload(teamId, file)))
    }

    async acceptForSend(
        teamId: number,
        refs: AttachmentRef[],
        needsUntil: Date
    ): Promise<AcceptedForSend | RefusedForSend> {
        const sizes = await Promise.all(refs.map((ref) => this.keepUntil('accept', teamId, ref.sha256, needsUntil)))
        const missing = refs.find((_, index) => sizes[index] === null)
        if (missing) {
            return { refusal: 'attachment_not_uploaded', sha256: missing.sha256 }
        }
        return { files: refs.map((ref, index) => ({ ...ref, sizeBytes: sizes[index]! })) }
    }

    async extend(teamId: number, sha256s: Sha256Hex[], needsUntil: Date): Promise<void> {
        await Promise.all(sha256s.map((sha256) => this.keepUntil('extend', teamId, sha256, needsUntil)))
    }

    async load(teamId: number, files: EmailAttachmentMetadata[], signal: AbortSignal): Promise<LoadedAttachment[]> {
        return await Promise.all(
            files.map(async (file) => ({
                file,
                bytes: await this.get(this.key(teamId, file.sha256), file.sha256, signal),
            }))
        )
    }

    private async prepareUpload(teamId: number, { sha256, size }: UploadRequest): Promise<UploadSlot> {
        const key = this.key(teamId, sha256)
        const head = await this.head(key)
        const expiresAt = head && expiryOf(head)
        if (expiresAt && expiresAt.getTime() - this.now().getTime() >= PRESENT_MIN_REMAINING_MS) {
            attachmentStoreFiles.labels({ operation: 'prepare', outcome: 'present' }).inc()
            return { sha256, status: 'present', expiresAt }
        }
        attachmentStoreFiles.labels({ operation: 'prepare', outcome: 'upload' }).inc()
        return await this.signUpload(key, sha256, size)
    }

    private async signUpload(key: string, sha256: Sha256Hex, size: number): Promise<UploadSlot> {
        const checksum = Buffer.from(sha256, 'hex').toString('base64')
        const urlExpiresAt = new Date(this.now().getTime() + UPLOAD_URL_LIFETIME_MS)
        try {
            const url = await settleBefore(
                AbortSignal.timeout(this.config.timeoutMs),
                getSignedUrl(
                    this.signer,
                    new PutObjectCommand({
                        Bucket: this.config.bucket,
                        Key: key,
                        ContentLength: size,
                        ChecksumSHA256: checksum,
                    }),
                    {
                        expiresIn: UPLOAD_URL_LIFETIME_MS / 1000,
                        // The checksum stays a signed header, so the bucket refuses a body whose SHA-256 differs from the key.
                        signableHeaders: new Set(['content-length', 'x-amz-checksum-sha256']),
                        unhoistableHeaders: new Set(['x-amz-checksum-sha256']),
                    }
                )
            )
            return {
                sha256,
                status: 'upload',
                url,
                method: 'PUT',
                headers: { 'Content-Length': String(size), 'x-amz-checksum-sha256': checksum },
                urlExpiresAt,
            }
        } catch (error) {
            throw new AttachmentStoreUnavailableError(error)
        }
    }

    private async keepUntil(
        operation: 'accept' | 'extend',
        teamId: number,
        sha256: Sha256Hex,
        needsUntil: Date
    ): Promise<number | null> {
        const key = this.key(teamId, sha256)
        const head = await this.head(key)
        if (!head || (head.ChecksumSHA256 && head.ChecksumSHA256 !== Buffer.from(sha256, 'hex').toString('base64'))) {
            attachmentStoreFiles.labels({ operation, outcome: 'missing' }).inc()
            return null
        }
        if (expiryOf(head) < needsUntil) {
            if (needsUntil > this.latestKeepable()) {
                throw new RangeError(
                    `A file can be kept until ${this.latestKeepable().toISOString()} at the latest, not ${needsUntil.toISOString()}`
                )
            }
            await this.copyOntoItself(key)
            attachmentStoreFiles.labels({ operation, outcome: 'copied' }).inc()
        } else {
            attachmentStoreFiles.labels({ operation, outcome: 'kept' }).inc()
        }
        return head.ContentLength ?? 0
    }

    // A self-copy keeps a file for one lifetime from the copy. S3 stores the copy's time to the second.
    private latestKeepable(): Date {
        return new Date(this.now().getTime() + ATTACHMENT_LIFETIME_MS - 1000)
    }

    private key(teamId: number, sha256: Sha256Hex): string {
        if (!SHA256_HEX.test(sha256)) {
            throw new Error(`The attachment hash ${JSON.stringify(sha256)} is not a SHA-256 in lowercase hex`)
        }
        return [this.config.prefix, 'team', teamId, sha256].filter((segment) => segment !== '').join('/')
    }

    private async head(key: string): Promise<HeadObjectCommandOutput | null> {
        const signal = AbortSignal.timeout(this.config.timeoutMs)
        try {
            return await settleBefore(
                signal,
                this.s3.send(new HeadObjectCommand({ Bucket: this.config.bucket, Key: key, ChecksumMode: 'ENABLED' }), {
                    abortSignal: signal,
                })
            )
        } catch (error) {
            if (error instanceof NotFound) {
                return null
            }
            throw new AttachmentStoreUnavailableError(error)
        }
    }

    private async copyOntoItself(key: string): Promise<void> {
        const { bucket } = this.config
        const signal = AbortSignal.timeout(this.config.timeoutMs)
        try {
            await settleBefore(
                signal,
                this.s3.send(
                    new CopyObjectCommand({
                        Bucket: bucket,
                        Key: key,
                        // S3 URL-decodes CopySource, unlike Key.
                        CopySource: `${bucket}/${key.split('/').map(encodeURIComponent).join('/')}`,
                        // S3 refuses a copy onto itself that changes nothing.
                        MetadataDirective: 'REPLACE',
                        ChecksumAlgorithm: 'SHA256',
                    }),
                    { abortSignal: signal }
                )
            )
        } catch (error) {
            throw new AttachmentStoreUnavailableError(error)
        }
    }

    private async get(key: string, sha256: Sha256Hex, signal: AbortSignal): Promise<Uint8Array> {
        try {
            const bytes = await settleBefore(
                signal,
                this.s3
                    .send(new GetObjectCommand({ Bucket: this.config.bucket, Key: key }), { abortSignal: signal })
                    .then((object) => object.Body!.transformToByteArray())
            )
            attachmentStoreFiles.labels({ operation: 'load', outcome: 'loaded' }).inc()
            return bytes
        } catch (error) {
            if (error instanceof NoSuchKey) {
                attachmentStoreFiles.labels({ operation: 'load', outcome: 'missing' }).inc()
                throw new AttachmentMissingError(sha256)
            }
            throw new AttachmentStoreUnavailableError(error)
        }
    }
}

const expiryOf = (head: HeadObjectCommandOutput): Date =>
    new Date((head.LastModified?.getTime() ?? 0) + ATTACHMENT_LIFETIME_MS)

// The SDK checks an abort signal only once a request goes out, so a credential refresh that stalls before it
// would hold the call past its deadline. Signing takes no signal at all.
export function settleBefore<T>(signal: AbortSignal, promise: Promise<T>): Promise<T> {
    return new Promise<T>((resolve, reject) => {
        const abort = (): void => {
            holdUntilSettled(promise)
            reject(signal.reason)
        }
        promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort))
        if (signal.aborted) {
            abort()
        } else {
            signal.addEventListener('abort', abort, { once: true })
        }
    })
}

type AttachmentStoreSettings = Pick<
    CdpConfig,
    | 'CDP_EMAIL_ATTACHMENTS_S3_BUCKET'
    | 'CDP_EMAIL_ATTACHMENTS_S3_REGION'
    | 'CDP_EMAIL_ATTACHMENTS_S3_PREFIX'
    | 'CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT'
    | 'CDP_EMAIL_ATTACHMENTS_S3_PUBLIC_ENDPOINT'
    | 'CDP_EMAIL_ATTACHMENTS_S3_ACCESS_KEY_ID'
    | 'CDP_EMAIL_ATTACHMENTS_S3_SECRET_ACCESS_KEY'
    | 'CDP_EMAIL_ATTACHMENTS_S3_TIMEOUT_MS'
>

type SigningCredentials = { accessKeyId: string; secretAccessKey: string; sessionToken?: string; expiration?: Date }
type SigningCredentialsProvider = (options?: { forceRefresh?: boolean }) => Promise<SigningCredentials>

const outlivesAnUploadUrl = ({ expiration }: SigningCredentials): boolean =>
    !expiration || expiration.getTime() - Date.now() >= SIGNING_CREDENTIALS_MIN_LIFETIME_MS

// The default chain answers a forced refresh without caching it, so the signer must keep the refreshed credentials.
// They are reported as expiring early, which makes the client's own refresh window as long as an upload URL needs.
export function credentialsThatOutliveUploadUrls(base: SigningCredentialsProvider): SigningCredentialsProvider {
    return async () => {
        const cached = await base()
        const credentials = outlivesAnUploadUrl(cached) ? cached : await base({ forceRefresh: true })
        if (!outlivesAnUploadUrl(credentials)) {
            throw new Error('The signing credentials expire before an upload URL would, even after a refresh')
        }
        return credentials.expiration
            ? {
                  ...credentials,
                  expiration: new Date(
                      credentials.expiration.getTime() -
                          SIGNING_CREDENTIALS_MIN_LIFETIME_MS +
                          S3_CLIENT_REFRESH_WINDOW_MS
                  ),
              }
            : credentials
    }
}

export function buildAttachmentStore(settings: AttachmentStoreSettings): S3AttachmentStore | null {
    if (!settings.CDP_EMAIL_ATTACHMENTS_S3_BUCKET) {
        return null
    }
    const staticCredentials =
        settings.CDP_EMAIL_ATTACHMENTS_S3_ACCESS_KEY_ID && settings.CDP_EMAIL_ATTACHMENTS_S3_SECRET_ACCESS_KEY
            ? {
                  accessKeyId: settings.CDP_EMAIL_ATTACHMENTS_S3_ACCESS_KEY_ID,
                  secretAccessKey: settings.CDP_EMAIL_ATTACHMENTS_S3_SECRET_ACCESS_KEY,
              }
            : undefined
    const client = (endpoint: string, credentials: S3ClientConfig['credentials']): S3Client =>
        new S3Client({
            region: settings.CDP_EMAIL_ATTACHMENTS_S3_REGION,
            credentials,
            ...(endpoint && { endpoint, forcePathStyle: true }),
        })
    return new S3AttachmentStore(
        client(settings.CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT, staticCredentials),
        client(
            settings.CDP_EMAIL_ATTACHMENTS_S3_PUBLIC_ENDPOINT || settings.CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT,
            staticCredentials ?? credentialsThatOutliveUploadUrls(defaultProvider())
        ),
        {
            bucket: settings.CDP_EMAIL_ATTACHMENTS_S3_BUCKET,
            prefix: settings.CDP_EMAIL_ATTACHMENTS_S3_PREFIX,
            timeoutMs: settings.CDP_EMAIL_ATTACHMENTS_S3_TIMEOUT_MS,
        }
    )
}
