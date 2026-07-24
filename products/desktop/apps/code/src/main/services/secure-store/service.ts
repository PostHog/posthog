import { SECURE_STORE_BACKEND } from "@main/di/tokens";
import { decrypt, encrypt } from "@main/utils/encryption";
import { logger } from "@main/utils/logger";
import { inject, injectable } from "inversify";

const log = logger.scope("secureStore");

/**
 * Minimal persistent key/value backend the service encrypts into. The Electron
 * host binds the electron-store `rendererStore` here; tests bind an in-memory
 * fake. Keeps the service host-agnostic and unit-testable without Electron.
 */
export interface SecureStoreBackend {
  has(key: string): boolean;
  get(key: string): unknown;
  set(key: string, value: string): void;
  delete(key: string): void;
  clear(): void;
}

/**
 * Backing service for the secure-store router: an encrypted-at-rest key/value
 * store. Values are machine-key encrypted before they touch the backend so the
 * persisted store never holds plaintext. All operations are best-effort and
 * never throw to the caller — a storage failure logs and degrades to a null
 * read / no-op write, matching the prior inline router behavior.
 */
@injectable()
export class SecureStoreService {
  constructor(
    @inject(SECURE_STORE_BACKEND)
    private readonly store: SecureStoreBackend,
  ) {}

  getItem(key: string): string | null {
    try {
      if (!this.store.has(key)) {
        return null;
      }
      return decrypt(this.store.get(key) as string);
    } catch (error) {
      log.error("Failed to get item:", error);
      return null;
    }
  }

  setItem(key: string, value: string): void {
    try {
      this.store.set(key, encrypt(value));
    } catch (error) {
      log.error("Failed to set item:", error);
    }
  }

  removeItem(key: string): void {
    try {
      this.store.delete(key);
    } catch (error) {
      log.error("Failed to remove item:", error);
    }
  }

  clear(): void {
    try {
      this.store.clear();
    } catch (error) {
      log.error("Failed to clear store:", error);
    }
  }
}
