export const RTK_VERSION = "0.43.0";

export const RTK_RELEASE_ASSETS = [
  {
    target: "aarch64-apple-darwin",
    archive: "rtk-aarch64-apple-darwin.tar.gz",
  },
  {
    target: "x86_64-apple-darwin",
    archive: "rtk-x86_64-apple-darwin.tar.gz",
  },
  {
    target: "aarch64-unknown-linux-gnu",
    archive: "rtk-aarch64-unknown-linux-gnu.tar.gz",
  },
  {
    target: "x86_64-unknown-linux-musl",
    archive: "rtk-x86_64-unknown-linux-musl.tar.gz",
  },
  {
    target: "x86_64-pc-windows-msvc",
    archive: "rtk-x86_64-pc-windows-msvc.zip",
  },
];

export function rtkTarget(platform = process.platform, arch = process.arch) {
  const targets = {
    darwin: {
      arm64: "aarch64-apple-darwin",
      x64: "x86_64-apple-darwin",
    },
    linux: {
      arm64: "aarch64-unknown-linux-gnu",
      x64: "x86_64-unknown-linux-musl",
    },
    win32: {
      x64: "x86_64-pc-windows-msvc",
    },
  };
  return targets[platform]?.[arch];
}

export function rtkAssetForTarget(target) {
  return RTK_RELEASE_ASSETS.find((asset) => asset.target === target);
}

export function rtkReleaseUrl(asset) {
  return `https://github.com/rtk-ai/rtk/releases/download/v${RTK_VERSION}/${asset.archive}`;
}
