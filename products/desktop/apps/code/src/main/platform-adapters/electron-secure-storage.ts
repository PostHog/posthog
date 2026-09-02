import type { ISecureStorage } from "@posthog/platform/secure-storage";
import { safeStorage } from "electron";
import { injectable } from "inversify";

@injectable()
export class ElectronSecureStorage implements ISecureStorage {
  public isAvailable(): boolean {
    return safeStorage.isEncryptionAvailable();
  }

  public async encryptString(text: string): Promise<Uint8Array> {
    const buffer = safeStorage.encryptString(text);
    return new Uint8Array(buffer.buffer, buffer.byteOffset, buffer.byteLength);
  }

  public async decryptString(data: Uint8Array): Promise<string> {
    return safeStorage.decryptString(Buffer.from(data));
  }
}
