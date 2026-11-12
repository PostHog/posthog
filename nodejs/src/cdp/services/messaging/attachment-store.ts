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
import { createHash } from 'node:crypto'
import { Counter } from 'prom-client'

import { CdpConfig } from '~/cdp/config'
import { EmailAttachmentMetadata } from '~/cdp/schema/cyclotron'

import { holdUntilSettled } from './in-flight-registry'

const MINUTE_MS = 60 * 1000
export const DAY_MS = 24 * 60 * MINUTE_MS
export const ATTACHMENT_LIFETIME_MS = 37 * DAY_MS
const LAST_MODIFIED_PRECISION_MS = 1000
const UPLOAD_URL_LIFETIME_MS = 15 * MINUTE_MS
const SIGNING_CREDENTIALS_MIN_LIFETIME_MS = UPLOAD_URL_LIFETIME_MS + MINUTE_MS
const S3_CLIENT_REFRESHES_CREDENTIALS_BEFORE_EXPIRY_MS = 5 * MINUTE_MS
const METADATA_REPLACED_SO_S3_ACCEPTS_A_SELF_COPY = 'REPLACE'
const DOWNLOADS_CHECKED_AGAINST_THEIR_HASH_SO_A_CUT_BODY_STILL_FAILS = 'WHEN_REQUIRED'
const PRESENT_MIN_REMAINING_MS = UPLOAD_URL_LIFETIME_MS + DAY_MS
export const SHA256_HEX = /^[0-9a-f]{64}$/

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
    acceptForSend(
        teamId: number,
        refs: AttachmentRef[],
        needsUntil: Date,
        deadline?: AbortSignal
    ): Promise<AcceptedForSend | RefusedForSend>
    load(teamId: number, files: EmailAttachmentMetadata[], signal: AbortSignal): Promise<LoadedAttachment[]>
}

const attachmentStoreFiles = new Counter({
    name: 'cdp_email_attachment_store_files_total',
    help: 'Files the email attachment store handled, by operation (prepare, accept, load) and outcome (present, upload, kept, copied, missing, loaded).',
    labelNames: ['operation', 'outcome'],
})

type S3AttachmentStoreConfig = { bucket: string; prefix: string; timeoutMs: number }

type StoredFile = { key: string; sizeBytes: number; expiresAt: Date }

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
        needsUntil: Date,
        deadline?: AbortSignal
    ): Promise<AcceptedForSend | RefusedForSend> {
        const found = await Promise.all(
            refs.map(async (ref) => ({ ref, stored: await this.storedFile(teamId, ref.sha256, deadline) }))
        )
        const present = found.filter((file): file is { ref: AttachmentRef; stored: StoredFile } => !!file.stored)
        const missing = found.find((file) => !file.stored)
        if (missing) {
            attachmentStoreFiles.labels({ operation: 'accept', outcome: 'missing' }).inc(found.length - present.length)
            return { refusal: 'attachment_not_uploaded', sha256: missing.ref.sha256 }
        }
        await this.keepUntil(
            present.map(({ stored }) => stored),
            needsUntil,
            deadline
        )
        return { files: present.map(({ ref, stored }) => ({ ...ref, sizeBytes: stored.sizeBytes })) }
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
        const stored = await this.storedFile(teamId, sha256)
        if (stored && stored.expiresAt.getTime() - this.now().getTime() >= PRESENT_MIN_REMAINING_MS) {
            attachmentStoreFiles.labels({ operation: 'prepare', outcome: 'present' }).inc()
            return { sha256, status: 'present', expiresAt: stored.expiresAt }
        }
        attachmentStoreFiles.labels({ operation: 'prepare', outcome: 'upload' }).inc()
        return await this.signUpload(this.key(teamId, sha256), sha256, size)
    }

    private async signUpload(key: string, sha256: Sha256Hex, size: number): Promise<UploadSlot> {
        const checksum = Buffer.from(sha256, 'hex').toString('base64')
        const urlExpiresAt = new Date(this.now().getTime() + UPLOAD_URL_LIFETIME_MS)
        try {
            const url = await settleBeforeAbortEvenWhileCredentialsStall(
                AbortSignal.timeout(this.config.timeoutMs),
                getSignedUrl(
                    this.signer,
                    new PutObjectCommand({
                        Bucket: this.config.bucket,
                        Key: key,
                        ContentLength: size,
                        ChecksumSHA256: checksum,
                    }),
                    { expiresIn: UPLOAD_URL_LIFETIME_MS / 1000, ...checksumSignedSoTheBucketRefusesAnotherBody() }
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

    private async storedFile(teamId: number, sha256: Sha256Hex, deadline?: AbortSignal): Promise<StoredFile | null> {
        const key = this.key(teamId, sha256)
        const head = await this.head(key, deadline)
        if (!head || (head.ChecksumSHA256 && head.ChecksumSHA256 !== Buffer.from(sha256, 'hex').toString('base64'))) {
            return null
        }
        return { key, sizeBytes: head.ContentLength ?? 0, expiresAt: expiryOf(head) }
    }

    private async keepUntil(files: StoredFile[], needsUntil: Date, deadline?: AbortSignal): Promise<void> {
        const toCopy = files.filter(({ expiresAt }) => expiresAt < needsUntil)
        if (toCopy.length && needsUntil > this.latestKeepable()) {
            throw new RangeError(
                `A file can be kept until ${this.latestKeepable().toISOString()} at the latest, not ${needsUntil.toISOString()}`
            )
        }
        deadline?.throwIfAborted()
        await Promise.all(toCopy.map(({ key }) => this.restartLifetimeBySelfCopy(key, deadline)))
        attachmentStoreFiles.labels({ operation: 'accept', outcome: 'copied' }).inc(toCopy.length)
        attachmentStoreFiles.labels({ operation: 'accept', outcome: 'kept' }).inc(files.length - toCopy.length)
    }

    private latestKeepable(): Date {
        return new Date(this.now().getTime() + ATTACHMENT_LIFETIME_MS - LAST_MODIFIED_PRECISION_MS)
    }

    private key(teamId: number, sha256: Sha256Hex): string {
        if (!SHA256_HEX.test(sha256)) {
            throw new Error(`The attachment hash ${JSON.stringify(sha256)} is not a SHA-256 in lowercase hex`)
        }
        return [this.config.prefix, 'team', teamId, sha256].filter((segment) => segment !== '').join('/')
    }

    private callSignal(deadline?: AbortSignal): AbortSignal {
        const timeout = AbortSignal.timeout(this.config.timeoutMs)
        return deadline ? AbortSignal.any([timeout, deadline]) : timeout
    }

    private async head(key: string, deadline?: AbortSignal): Promise<HeadObjectCommandOutput | null> {
        const signal = this.callSignal(deadline)
        try {
            return await settleBeforeAbortEvenWhileCredentialsStall(
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

    private async restartLifetimeBySelfCopy(key: string, deadline?: AbortSignal): Promise<void> {
        const { bucket } = this.config
        const signal = this.callSignal(deadline)
        try {
            await settleBeforeAbortEvenWhileCredentialsStall(
                signal,
                this.s3.send(
                    new CopyObjectCommand({
                        Bucket: bucket,
                        Key: key,
                        CopySource: urlEncodedCopySource(bucket, key),
                        MetadataDirective: METADATA_REPLACED_SO_S3_ACCEPTS_A_SELF_COPY,
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
            const bytes = await settleBeforeAbortEvenWhileCredentialsStall(
                signal,
                this.s3
                    .send(new GetObjectCommand({ Bucket: this.config.bucket, Key: key }), { abortSignal: signal })
                    .then((object) => object.Body!.transformToByteArray())
                    .then((downloaded) => matchingItsHash(downloaded, sha256))
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

function matchingItsHash(bytes: Uint8Array, sha256: Sha256Hex): Uint8Array {
    if (createHash('sha256').update(bytes).digest('hex') !== sha256) {
        throw new Error(`The bytes downloaded for ${sha256} do not match its hash`)
    }
    return bytes
}

const expiryOf = (head: HeadObjectCommandOutput): Date =>
    new Date((head.LastModified?.getTime() ?? 0) + ATTACHMENT_LIFETIME_MS)

const checksumSignedSoTheBucketRefusesAnotherBody = (): {
    signableHeaders: Set<string>
    unhoistableHeaders: Set<string>
} => ({
    signableHeaders: new Set(['content-length', 'x-amz-checksum-sha256']),
    unhoistableHeaders: new Set(['x-amz-checksum-sha256']),
})

const urlEncodedCopySource = (bucket: string, key: string): string =>
    `${bucket}/${key.split('/').map(encodeURIComponent).join('/')}`

export function settleBeforeAbortEvenWhileCredentialsStall<T>(signal: AbortSignal, promise: Promise<T>): Promise<T> {
    holdUntilSettled(promise)
    return new Promise<T>((resolve, reject) => {
        const abort = (): void => reject(signal.reason)
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

const expiringWhenTheClientMustRefreshThemForAnUploadUrl = (credentials: SigningCredentials): SigningCredentials =>
    credentials.expiration
        ? {
              ...credentials,
              expiration: new Date(
                  credentials.expiration.getTime() -
                      SIGNING_CREDENTIALS_MIN_LIFETIME_MS +
                      S3_CLIENT_REFRESHES_CREDENTIALS_BEFORE_EXPIRY_MS
              ),
          }
        : credentials

export function credentialsThatOutliveUploadUrls(base: SigningCredentialsProvider): SigningCredentialsProvider {
    return async () => {
        const cached = await base()
        const credentials = outlivesAnUploadUrl(cached) ? cached : await base({ forceRefresh: true })
        if (!outlivesAnUploadUrl(credentials)) {
            throw new Error('The signing credentials expire before an upload URL would, even after a refresh')
        }
        return expiringWhenTheClientMustRefreshThemForAnUploadUrl(credentials)
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
            responseChecksumValidation: DOWNLOADS_CHECKED_AGAINST_THEIR_HASH_SO_A_CUT_BODY_STILL_FAILS,
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
