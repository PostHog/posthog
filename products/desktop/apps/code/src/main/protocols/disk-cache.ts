import { electronNetFetch } from "@main/platform-adapters/electron-net-fetch";
import {
  CACHED_IMAGE_NAMESPACE_MAX_BYTES,
  createCachedImageHandler,
} from "@main/services/disk-cache/images";
import type { DiskCache } from "@main/services/disk-cache/service";
import { DISK_CACHE_SCHEME } from "@shared/disk-cache-protocol";
import { session } from "electron";

export function registerDiskCacheProtocol(diskCache: DiskCache): void {
  session.fromPartition("persist:main").protocol.handle(
    DISK_CACHE_SCHEME,
    createCachedImageHandler(
      diskCache.namespace("images", {
        maxBytes: CACHED_IMAGE_NAMESPACE_MAX_BYTES,
      }),
      electronNetFetch,
    ),
  );
}
