import { logger } from "@main/utils/logger";
import {
  type ISecureStorage,
  SECURE_STORAGE_SERVICE,
} from "@posthog/platform/secure-storage";
import { inject, injectable } from "inversify";

const log = logger.scope("encryption");

/**
 * Backing service for the encryption router: base64-transports values through
 * the host secure-storage cipher, falling back to passthrough when the host has
 * no secure storage available. Owns the availability check + base64 framing +
 * error handling that previously lived inline in the router. Best-effort: a
 * cipher failure logs and returns null rather than throwing to the renderer.
 */
@injectable()
export class EncryptionService {
  constructor(
    @inject(SECURE_STORAGE_SERVICE)
    private readonly secureStorage: ISecureStorage,
  ) {}

  async encrypt(stringToEncrypt: string): Promise<string | null> {
    try {
      if (this.secureStorage.isAvailable()) {
        const encrypted =
          await this.secureStorage.encryptString(stringToEncrypt);
        return Buffer.from(encrypted).toString("base64");
      }
      return stringToEncrypt;
    } catch (error) {
      log.error("Failed to encrypt string:", error);
      return null;
    }
  }

  async decrypt(stringToDecrypt: string): Promise<string | null> {
    try {
      if (this.secureStorage.isAvailable()) {
        const bytes = new Uint8Array(Buffer.from(stringToDecrypt, "base64"));
        return await this.secureStorage.decryptString(bytes);
      }
      return stringToDecrypt;
    } catch (error) {
      log.error("Failed to decrypt string:", error);
      return null;
    }
  }
}
