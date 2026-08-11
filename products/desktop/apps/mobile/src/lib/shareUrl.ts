import { isSafeExternalUrl } from "@posthog/shared";
import { Platform, Share } from "react-native";
import { logger } from "@/lib/logger";

const log = logger.scope("shareUrl");

/**
 * Opens the native share sheet for a URL — the route to "Save to Files",
 * AirDrop, or any other app. iOS treats `url` as a first-class attachment;
 * Android has no URL field, so the link travels in `message`.
 */
export async function shareUrl(url: string, title?: string): Promise<void> {
  if (!isSafeExternalUrl(url)) {
    log.warn("Blocked share of URL with unsafe scheme", url);
    return;
  }

  await Share.share(
    Platform.OS === "ios"
      ? { url, ...(title ? { title } : {}) }
      : { message: url, ...(title ? { title } : {}) },
  );
}
