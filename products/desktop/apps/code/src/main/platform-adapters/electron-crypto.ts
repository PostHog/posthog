import { createHash, randomBytes } from "node:crypto";
import type { ICrypto } from "@posthog/platform/crypto";
import { injectable } from "inversify";

@injectable()
export class ElectronCrypto implements ICrypto {
  randomBase64Url(byteLength: number): string {
    return randomBytes(byteLength).toString("base64url");
  }

  sha256Base64Url(input: string): string {
    return createHash("sha256").update(input).digest("base64url");
  }
}
