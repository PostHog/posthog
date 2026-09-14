const REQUIRED_LICENSE_MARKERS = [
  "MIT License",
  "Permission is hereby granted, free of charge",
  'THE SOFTWARE IS PROVIDED "AS IS"',
];

export function assertMitLicense(license: string): void {
  for (const marker of REQUIRED_LICENSE_MARKERS) {
    if (!license.includes(marker)) {
      throw new Error(
        `Benjamin-Plus license is missing the required MIT marker: "${marker}"`,
      );
    }
  }

  if (license.includes("*/")) {
    throw new Error(
      "Benjamin-Plus license contains a block-comment terminator",
    );
  }
}
