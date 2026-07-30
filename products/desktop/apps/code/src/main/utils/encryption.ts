import crypto from "node:crypto";
import os from "node:os";
import { machineIdSync } from "node-machine-id";

// Key derived from hardware UUID - data only decryptable on this machine
// No keychain prompts, prevents token theft via cloud sync/backups
// TODO: Migrate to posthog-code
const APP_SALT = "array-v1";
const ENCRYPTION_VERSION = 1;

let cachedMachineKey: Buffer | undefined;

function getMachineKey(): Buffer {
  if (!cachedMachineKey) {
    const machineId = machineIdSync();
    const identifier = [machineId, os.platform(), os.arch()].join("|");
    cachedMachineKey = crypto.scryptSync(identifier, APP_SALT, 32);
  }
  return cachedMachineKey;
}

export function encrypt(plaintext: string): string {
  const key = getMachineKey();
  const iv = crypto.randomBytes(16);
  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);

  const encrypted = Buffer.concat([
    cipher.update(plaintext, "utf8"),
    cipher.final(),
  ]);
  const authTag = cipher.getAuthTag();

  return JSON.stringify({
    v: ENCRYPTION_VERSION,
    iv: iv.toString("base64"),
    data: encrypted.toString("base64"),
    tag: authTag.toString("base64"),
  });
}

export function decrypt(encryptedJson: string): string | null {
  try {
    const { iv, data, tag } = JSON.parse(encryptedJson);
    const key = getMachineKey();
    const decipher = crypto.createDecipheriv(
      "aes-256-gcm",
      key,
      Buffer.from(iv, "base64"),
    );
    decipher.setAuthTag(Buffer.from(tag, "base64"));

    return decipher.update(data, "base64", "utf8") + decipher.final("utf8");
  } catch {
    return null;
  }
}
