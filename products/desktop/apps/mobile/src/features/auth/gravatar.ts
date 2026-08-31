import * as Crypto from "expo-crypto";

export type ImageProbeResult = "unknown" | "loaded" | "failed";
export type ProfilePictureStatus = "unknown" | "found" | "missing";

export const DEFAULT_GRAVATAR_SIZE = 144;
export const GRAVATAR_MANAGE_URL = "https://gravatar.com/profile/avatars";

export async function buildGravatarUrl(
  email: string | null | undefined,
  size: number = DEFAULT_GRAVATAR_SIZE,
): Promise<string | undefined> {
  if (!email) return undefined;
  const normalized = email.trim().toLowerCase();
  if (!normalized) return undefined;
  const hash = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    normalized,
  );
  // `d=404` makes Gravatar return 404 rather than a default silhouette, so a
  // missing picture falls back to initials.
  return `https://www.gravatar.com/avatar/${hash}?s=${size}&d=404`;
}

export function mapProbeResultToStatus(
  result: ImageProbeResult,
): ProfilePictureStatus {
  switch (result) {
    case "loaded":
      return "found";
    case "failed":
      return "missing";
    case "unknown":
      return "unknown";
  }
}

export function profilePictureDescription(
  status: ProfilePictureStatus,
  email: string,
): string {
  switch (status) {
    case "unknown":
      return `Checking Gravatar for ${email}`;
    case "found":
      return `Comes from Gravatar, matched to ${email}. Change it there, then refresh to see it here.`;
    case "missing":
      return `No picture yet. Add one on Gravatar for ${email} and it shows here and anywhere teammates see you.`;
  }
}
