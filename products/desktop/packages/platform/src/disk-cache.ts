export interface IDiskCache {
  clear(): Promise<void>;
}

export const DISK_CACHE_SERVICE = Symbol.for("posthog.platform.diskCache");

export interface IDiskCacheImages {
  imageUrl(remoteUrl: string): string;
}

export const DISK_CACHE_IMAGES = Symbol.for("posthog.platform.diskCacheImages");
