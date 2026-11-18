const MAX_FEEDBACK_IMAGE_INPUT_BYTES = 10 * 1024 * 1024;
const MAX_FEEDBACK_IMAGE_BYTES = 160 * 1024;
const FEEDBACK_IMAGE_WIDTHS = [1_200, 900, 720];
const FEEDBACK_IMAGE_QUALITIES = [0.7, 0.55, 0.4];
const SUPPORTED_IMAGE_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
]);

export const MAX_FEEDBACK_IMAGE_COUNT = 2;

export interface FeedbackImage {
  id: string;
  name: string;
  dataUrl: string;
}

async function detectImageType(file: File): Promise<string | null> {
  const bytes = await new Promise<Uint8Array>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (reader.result instanceof ArrayBuffer) {
        resolve(new Uint8Array(reader.result));
      } else {
        reject(new Error("Could not read this image."));
      }
    };
    reader.onerror = () => reject(new Error("Could not read this image."));
    reader.readAsArrayBuffer(file.slice(0, 12));
  });
  if ([0xff, 0xd8, 0xff].every((byte, index) => bytes[index] === byte)) {
    return "image/jpeg";
  }
  if (
    [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a].every(
      (byte, index) => bytes[index] === byte,
    )
  ) {
    return "image/png";
  }
  if (
    String.fromCharCode(...bytes.slice(0, 4)) === "RIFF" &&
    String.fromCharCode(...bytes.slice(8, 12)) === "WEBP"
  ) {
    return "image/webp";
  }
  return null;
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        resolve(reader.result);
      } else {
        reject(new Error("Could not read this image."));
      }
    };
    reader.onerror = () => reject(new Error("Could not read this image."));
    reader.readAsDataURL(blob);
  });
}

function canvasToBlob(
  canvas: HTMLCanvasElement,
  quality: number,
): Promise<Blob | null> {
  return new Promise((resolve) => {
    canvas.toBlob(resolve, "image/jpeg", quality);
  });
}

async function resizeImage(file: File): Promise<string> {
  const bitmap = await createImageBitmap(file);
  try {
    for (let index = 0; index < FEEDBACK_IMAGE_WIDTHS.length; index += 1) {
      const scale = Math.min(1, FEEDBACK_IMAGE_WIDTHS[index] / bitmap.width);
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      const context = canvas.getContext("2d");
      if (!context) break;
      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);

      const blob = await canvasToBlob(canvas, FEEDBACK_IMAGE_QUALITIES[index]);
      if (blob && blob.size <= MAX_FEEDBACK_IMAGE_BYTES) {
        return blobToDataUrl(blob);
      }
    }
  } finally {
    bitmap.close();
  }

  throw new Error("Could not resize this image. Try a smaller file.");
}

export async function readFeedbackImage(file: File): Promise<FeedbackImage> {
  if (file.type && !SUPPORTED_IMAGE_TYPES.has(file.type)) {
    throw new Error("Choose a JPEG, PNG, or WebP image.");
  }
  if (file.size > MAX_FEEDBACK_IMAGE_INPUT_BYTES) {
    throw new Error("Choose an image smaller than 10 MB.");
  }
  const detectedType = await detectImageType(file);
  if (!detectedType || (file.type && file.type !== detectedType)) {
    throw new Error("Choose a JPEG, PNG, or WebP image.");
  }

  return {
    id: `${file.name}:${file.size}:${file.lastModified}`,
    name: file.name,
    dataUrl: await resizeImage(file),
  };
}
