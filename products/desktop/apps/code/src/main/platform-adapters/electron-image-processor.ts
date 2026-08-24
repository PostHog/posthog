import type {
  DownscaledImage,
  DownscaleOptions,
  IImageProcessor,
} from "@posthog/platform/image-processor";
import { nativeImage } from "electron";
import { injectable } from "inversify";

@injectable()
export class ElectronImageProcessor implements IImageProcessor {
  public downscale(
    raw: Uint8Array,
    mimeType: string,
    options: DownscaleOptions,
  ): DownscaledImage {
    const image = nativeImage.createFromBuffer(Buffer.from(raw));
    const fallbackExtension = mimeType.split("/")[1] || "png";

    if (image.isEmpty()) {
      return { buffer: raw, mimeType, extension: fallbackExtension };
    }

    const { width, height } = image.getSize();
    const maxDim = Math.max(width, height);

    if (maxDim <= options.maxDimension) {
      return { buffer: raw, mimeType, extension: fallbackExtension };
    }

    const scale = options.maxDimension / maxDim;
    const resized = image.resize({
      width: Math.round(width * scale),
      height: Math.round(height * scale),
      quality: "best",
    });

    const preserveAlpha =
      options.preserveAlpha ??
      (mimeType === "image/png" || mimeType === "image/webp");

    if (preserveAlpha) {
      return {
        buffer: resized.toPNG(),
        mimeType: "image/png",
        extension: "png",
      };
    }

    return {
      buffer: resized.toJPEG(options.jpegQuality ?? 85),
      mimeType: "image/jpeg",
      extension: "jpeg",
    };
  }
}
