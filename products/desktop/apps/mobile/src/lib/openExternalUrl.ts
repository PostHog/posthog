import { isSafeExternalUrl } from "@posthog/shared";
import { Linking } from "react-native";
import { logger } from "@/lib/logger";

const log = logger.scope("openExternalUrl");

export function openExternalUrl(url: string): void {
  if (!isSafeExternalUrl(url)) {
    log.warn("Blocked external URL with unsafe scheme", url);
    return;
  }
  void Linking.openURL(url).catch(() => {});
}
