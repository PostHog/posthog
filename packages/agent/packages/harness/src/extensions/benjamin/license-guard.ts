export function assertMitLicense(license: string): void {
  const required = [
    "MIT License",
    "Permission is hereby granted, free of charge",
    'THE SOFTWARE IS PROVIDED "AS IS"',
  ];
  for (const marker of required) {
    if (!license.includes(marker)) {
      throw new Error(
        `Upstream LICENSE no longer looks like the expected MIT license (missing "${marker}") - review it before syncing`,
      );
    }
  }
  if (license.includes("*/")) {
    throw new Error(
      'Upstream LICENSE contains a block-comment terminator ("*/"), which would escape the generated banner and execute as code - review it before syncing',
    );
  }
}
