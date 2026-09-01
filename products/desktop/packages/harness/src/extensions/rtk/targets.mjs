export const RTK_VERSION = "0.43.0";

export const RTK_RELEASE_ASSETS = [
  {
    target: "aarch64-apple-darwin",
    archive: "rtk-aarch64-apple-darwin.tar.gz",
    checksum:
      "8a17e49acbd378997eb21d0eb6f7f861111f35b4fc9b1c74edf4c7448e576c65",
  },
  {
    target: "x86_64-apple-darwin",
    archive: "rtk-x86_64-apple-darwin.tar.gz",
    checksum:
      "a85f60e2637811be68366208b8d8b9c5ba1b748cb5df4477ab20cd73d3c5d9f8",
  },
  {
    target: "aarch64-unknown-linux-gnu",
    archive: "rtk-aarch64-unknown-linux-gnu.tar.gz",
    checksum:
      "5519f7ca12e5c143a609f0d28a0a77b97413a8dce31c2681f1a41c24519a8731",
  },
  {
    target: "x86_64-unknown-linux-musl",
    archive: "rtk-x86_64-unknown-linux-musl.tar.gz",
    checksum:
      "ff8a1e7766496e175291a85aeca1dc97c9ff6df33e51e5893d1fbc78fea2a609",
  },
  {
    target: "x86_64-pc-windows-msvc",
    archive: "rtk-x86_64-pc-windows-msvc.zip",
    checksum:
      "7c5e4a2ef816a4d4ed947ddd74ca3df851fc39ea87d49a3ca2bf3abc515a016b",
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
