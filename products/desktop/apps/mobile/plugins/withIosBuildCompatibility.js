const {
  withPodfileProperties,
  withXcodeProject,
} = require("expo/config-plugins");
const fs = require("node:fs");
const path = require("node:path");

module.exports = function withIosBuildCompatibility(config) {
  config = withPodfileProperties(config, (cfg) => {
    // ExpoVideo's precompiled binary references a symbol absent from ExpoModulesCore 57.0.7.
    cfg.modResults.EXPO_USE_PRECOMPILED_MODULES = "false";
    return cfg;
  });
  return withXcodeProject(config, (cfg) => {
    const name = cfg.modRequest.projectName;
    const schemes = path.join(
      cfg.modRequest.platformProjectRoot,
      `${name}.xcodeproj`,
      "xcshareddata/xcschemes",
    );
    // The PostHog SDK pod also exports a PostHog scheme; CLI builds can select the library.
    fs.copyFileSync(
      path.join(schemes, `${name}.xcscheme`),
      path.join(schemes, "PostHogMobile.xcscheme"),
    );
    return cfg;
  });
};
