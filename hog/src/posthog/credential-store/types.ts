import { z } from 'zod'

import type { Host } from '@/posthog/host'
import type { OAuthAccessToken, OAuthRefreshToken, PersonalApiKey } from '@/posthog/tokens'

// The part of a login the credential store keeps. settings.json keeps the rest, so a keychain item
// stays small however many scopes a login gains.
export interface PersonalAPIKeySecret {
    apiKey: PersonalApiKey
}

export interface OAuthSecret {
    accessToken: OAuthAccessToken
    refreshToken: OAuthRefreshToken
}

export type StoredSecret = PersonalAPIKeySecret | OAuthSecret

export type StoreKind = 'keychain' | 'file' | 'memory'

// The stores a login can use. The memory store exists for tests only.
export const StoreChoiceSchema = z.enum(['keychain', 'file'])

export type StoreChoice = z.output<typeof StoreChoiceSchema>

// Where hog keeps the secrets of the logins `hog auth login` saves, one per host.
export interface CredentialStore {
    readonly kind: StoreKind
    // The file that holds the secrets. Null for a store that isn't a file.
    readonly path: string | null
    read(host: Host): Promise<StoredSecret | undefined>
    // `removeIfLate` is for a caller that stops using this store when the write times out: a write
    // that still lands afterwards is removed again, so no item outlives what settings.json records.
    write(host: Host, secret: StoredSecret, options?: { removeIfLate?: boolean }): Promise<void>
    // Resolves to false when the store held nothing for the host.
    remove(host: Host): Promise<boolean>
}
