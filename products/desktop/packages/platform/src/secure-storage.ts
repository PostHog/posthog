export interface ISecureStorage {
  isAvailable(): boolean;
  encryptString(text: string): Promise<Uint8Array>;
  decryptString(data: Uint8Array): Promise<string>;
}

export const SECURE_STORAGE_SERVICE = Symbol.for(
  "posthog.platform.secureStorage",
);
