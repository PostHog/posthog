import type { ClaudeSubscriptionTokenStore } from "@posthog/core/cloud-task/identifiers";
import { safeStorage } from "electron";
import type { SecureStoreBackend } from "../services/secure-store/service";

export class ElectronClaudeSubscriptionTokenStore
  implements ClaudeSubscriptionTokenStore
{
  constructor(private readonly store: SecureStoreBackend) {}

  private requireEncryption(): void {
    if (
      !safeStorage.isEncryptionAvailable() ||
      (process.platform === "linux" &&
        safeStorage.getSelectedStorageBackend() === "basic_text")
    ) {
      throw new Error(
        "Secure storage is not available. Unlock your system key store and try again.",
      );
    }
  }

  async get(): Promise<string | null> {
    this.requireEncryption();
    if (this.store.has("token")) {
      const encrypted = this.store.get("token");
      if (typeof encrypted !== "string") {
        throw new Error("Cannot read the saved Claude token.");
      }
      try {
        return safeStorage.decryptString(Buffer.from(encrypted, "base64"));
      } catch {
        throw new Error(
          "Cannot read the token. Unlock your system key store. If the error continues, replace or remove the token.",
        );
      }
    }
    return null;
  }

  async save(token: string): Promise<void> {
    this.requireEncryption();
    try {
      const encrypted = safeStorage.encryptString(token).toString("base64");
      this.store.set("token", encrypted);
      if (this.store.get("token") !== encrypted)
        throw new Error("Write failed");
    } catch {
      throw new Error(
        "Cannot save the token. Check your system key store and try again.",
      );
    }
  }

  async clear(): Promise<void> {
    this.store.delete("token");
    if (this.store.has("token")) {
      throw new Error("Could not remove the Claude token. Try again.");
    }
  }

  async has(): Promise<boolean> {
    return (await this.get()) !== null;
  }
}
