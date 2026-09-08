import { createHash, randomUUID } from "node:crypto";
import {
  mkdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import type { ClaudeSubscriptionTokenStore } from "@posthog/core/cloud-task/identifiers";
import { safeStorage } from "electron";

export class ElectronClaudeSubscriptionTokenStore
  implements ClaudeSubscriptionTokenStore
{
  constructor(
    private readonly directory: string,
    private readonly getAccountKey: () => Promise<string | null>,
  ) {}

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

  private async tokenPath(expectedAccountKey?: string): Promise<string> {
    const accountKey = await this.getAccountKey();
    if (
      !accountKey ||
      (expectedAccountKey !== undefined && accountKey !== expectedAccountKey)
    ) {
      throw new Error("Sign in to the account that owns this Claude token.");
    }
    return join(
      this.directory,
      createHash("sha256").update(accountKey).digest("hex"),
    );
  }

  async get(expectedAccountKey?: string): Promise<string | null> {
    const file = await this.tokenPath(expectedAccountKey);
    this.requireEncryption();
    let encrypted: Buffer;
    try {
      encrypted = readFileSync(file);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
      throw new Error("Cannot read the saved Claude token.");
    }
    try {
      return safeStorage.decryptString(encrypted);
    } catch {
      throw new Error(
        "Cannot read the token. Unlock your system key store. If the error continues, replace or remove the token.",
      );
    }
  }

  async save(token: string): Promise<void> {
    const file = await this.tokenPath();
    this.requireEncryption();
    const temporary = `${file}.${randomUUID()}.tmp`;
    try {
      const encrypted = safeStorage.encryptString(token);
      mkdirSync(this.directory, { recursive: true, mode: 0o700 });
      writeFileSync(temporary, encrypted, { flag: "wx", mode: 0o600 });
      renameSync(temporary, file);
    } catch {
      throw new Error(
        "Cannot save the token. Check your system key store and try again.",
      );
    } finally {
      rmSync(temporary, { force: true });
    }
  }

  async clear(): Promise<void> {
    rmSync(await this.tokenPath(), { force: true });
  }

  async clearAll(): Promise<void> {
    rmSync(this.directory, { recursive: true, force: true });
  }

  async has(): Promise<boolean> {
    return (await this.get()) !== null;
  }
}
