// Xcode 14+ refuses to build resource-bundle targets that don't have a
// development team set. Several common Pods (react-native-svg in
// particular) ship bundles without a team and break EAS builds with:
//
//   "Starting from Xcode 14, resource bundles are signed by default,
//    which requires setting the development team for each resource
//    bundle target."
//
// Disabling code signing for those bundle targets is the standard
// workaround — they don't actually need to be signed because the host
// app's signature covers them at runtime.
//
// Injecting this via a config plugin (instead of hand-editing Podfile)
// means `expo prebuild --clean` won't wipe the fix.

const { withDangerousMod } = require("@expo/config-plugins");
const fs = require("node:fs");
const path = require("node:path");

const MARKER = "# CODE_SIGNING_ALLOWED resource-bundle fix";

const POST_INSTALL_SNIPPET = `
    ${MARKER}
    installer.pods_project.targets.each do |target|
      if target.respond_to?(:product_type) && target.product_type == "com.apple.product-type.bundle"
        target.build_configurations.each do |config|
          config.build_settings["CODE_SIGNING_ALLOWED"] = "NO"
        end
      end
    end
`;

const withPodfileResourceBundleFix = (config) =>
  withDangerousMod(config, [
    "ios",
    async (cfg) => {
      const podfilePath = path.join(
        cfg.modRequest.platformProjectRoot,
        "Podfile",
      );
      const contents = fs.readFileSync(podfilePath, "utf8");

      if (contents.includes(MARKER)) {
        return cfg;
      }

      // Inject the snippet at the END of the existing post_install block.
      // The block opens with `post_install do |installer|` and closes at
      // the matching `end` — we find the closing `end` of that block by
      // tracking nesting depth.
      const startMatch = contents.match(/post_install do \|installer\|/);
      if (!startMatch) {
        throw new Error(
          "[withPodfileResourceBundleFix] could not find a post_install block to patch",
        );
      }
      const startIdx = startMatch.index + startMatch[0].length;
      const lines = contents.slice(startIdx).split("\n");
      let depth = 1;
      let endLineOffset = -1;
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        // crude but sufficient for the generated Podfile shape
        if (
          /\bdo\b/.test(line) ||
          /^(if|begin|case|class|def|module)\b/.test(line)
        ) {
          depth += 1;
        }
        if (/^end\b/.test(line)) {
          depth -= 1;
          if (depth === 0) {
            endLineOffset = i;
            break;
          }
        }
      }
      if (endLineOffset === -1) {
        throw new Error(
          "[withPodfileResourceBundleFix] could not find the end of the post_install block",
        );
      }

      // Insert our snippet just before that closing `end`.
      const insertAt =
        startIdx +
        lines.slice(0, endLineOffset).join("\n").length +
        (endLineOffset > 0 ? 1 : 0);
      const patched =
        contents.slice(0, insertAt) +
        POST_INSTALL_SNIPPET +
        contents.slice(insertAt);

      fs.writeFileSync(podfilePath, patched, "utf8");
      return cfg;
    },
  ]);

module.exports = withPodfileResourceBundleFix;
