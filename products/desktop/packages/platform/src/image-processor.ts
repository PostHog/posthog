export interface DownscaleOptions {
  maxDimension: number;
  jpegQuality?: number;
  /**
   * Hint that source image has an alpha channel — encoder should preserve it.
   * When true, output is PNG. When false, output is JPEG (smaller for photos).
   */
  preserveAlpha?: boolean;
}

export interface DownscaledImage {
  buffer: Uint8Array;
  mimeType: string;
  extension: string;
}

export interface IImageProcessor {
  /**
   * Downscale an image to fit within `maxDimension` on the longest side.
   * If already small enough, returns the original buffer/mimeType unchanged.
   */
  downscale(
    raw: Uint8Array,
    mimeType: string,
    options: DownscaleOptions,
  ): DownscaledImage;
}

export const IMAGE_PROCESSOR_SERVICE = Symbol.for(
  "posthog.platform.imageProcessor",
);
