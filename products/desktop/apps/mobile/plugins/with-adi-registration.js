const { withDangerousMod } = require("expo/config-plugins");
const fs = require("node:fs");
const path = require("node:path");

const ADI_SNIPPET = "D4HHLU7245454AAAAAAAAAAAAA";

module.exports = function withAdiRegistration(config) {
  return withDangerousMod(config, [
    "android",
    async (cfg) => {
      const assetsDir = path.join(
        cfg.modRequest.platformProjectRoot,
        "app",
        "src",
        "main",
        "assets",
      );
      fs.mkdirSync(assetsDir, { recursive: true });
      fs.writeFileSync(
        path.join(assetsDir, "adi-registration.properties"),
        ADI_SNIPPET,
      );
      return cfg;
    },
  ]);
};
