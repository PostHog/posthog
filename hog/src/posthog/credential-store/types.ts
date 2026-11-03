// The part of a login the credential store keeps. settings.json keeps the rest, so a keychain item
// stays small however many scopes a login gains.
export interface PersonalAPIKeySecret {
    apiKey: string
}

export type StoredSecret = PersonalAPIKeySecret

export type StoreKind = 'keychain' | 'file' | 'memory'

// The stores a login can use. The memory store exists for tests only.
export type StoreChoice = Exclude<StoreKind, 'memory'>

// Where hog keeps the secrets of the logins `hog auth login` saves, one per host. Commands only see
// this interface, so each store behaves the same to them.
export interface CredentialStore {
    readonly kind: StoreKind
    // The file that holds the secrets. Null for a store that isn't a file.
    readonly path: string | null
    read(host: string): Promise<StoredSecret | undefined>
    write(host: string, secret: StoredSecret): Promise<void>
    // Resolves to false when the store held nothing for the host.
    remove(host: string): Promise<boolean>
}
