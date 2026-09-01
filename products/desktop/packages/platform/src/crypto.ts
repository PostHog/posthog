/**
 * Host crypto/random capability. Keeps node:crypto out of core (PKCE, ids,
 * hashes). Each host implements it natively (Electron/Node via node:crypto, a
 * web host via Web Crypto).
 */
export interface ICrypto {
  /** Cryptographically-random bytes, base64url-encoded. */
  randomBase64Url(byteLength: number): string;
  /** SHA-256 digest of the input string, base64url-encoded. */
  sha256Base64Url(input: string): string;
}

export const CRYPTO_SERVICE = Symbol.for("posthog.platform.crypto");
