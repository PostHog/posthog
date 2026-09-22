import type { IDiskCacheImages } from "@posthog/platform/disk-cache";
import {
  isCacheableImageUrl,
  toCachedImageUrl,
} from "@shared/disk-cache-protocol";

export const desktopDiskCacheImages: IDiskCacheImages = {
  imageUrl: (remoteUrl) =>
    isCacheableImageUrl(remoteUrl) ? toCachedImageUrl(remoteUrl) : remoteUrl,
};
