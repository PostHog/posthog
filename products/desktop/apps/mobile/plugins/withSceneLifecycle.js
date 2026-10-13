const { withAppDelegate, withInfoPlist } = require("expo/config-plugins");
const fs = require("node:fs");
const path = require("node:path");

const startup =
  / {4}window = UIWindow\(frame: UIScreen\.main\.bounds\)\s+factory\.startReactNative\(\s+withModuleName: "main",\s+in: window,\s+launchOptions: launchOptions\)/;

module.exports = function withSceneLifecycle(config) {
  config = withInfoPlist(config, (cfg) => {
    cfg.modResults.UIApplicationSceneManifest = {
      UIApplicationSupportsMultipleScenes: false,
      UISceneConfigurations: {
        UIWindowSceneSessionRoleApplication: [
          {
            UISceneConfigurationName: "Default Configuration",
            UISceneDelegateClassName:
              "$(PRODUCT_MODULE_NAME).PostHogSceneDelegate",
          },
        ],
      },
    };
    return cfg;
  });

  return withAppDelegate(config, (cfg) => {
    if (cfg.modResults.language !== "swift") {
      throw new Error("withSceneLifecycle requires a Swift AppDelegate");
    }
    const contents = cfg.modResults.contents;
    if (contents.includes("class PostHogSceneDelegate:")) {
      return cfg;
    }
    if (!startup.test(contents)) {
      throw new Error(
        "Expo AppDelegate startup changed; review withSceneLifecycle before building",
      );
    }
    if (!contents.includes("  var window: UIWindow?")) {
      throw new Error(
        "Expo AppDelegate window declaration changed; review withSceneLifecycle before building",
      );
    }
    cfg.modResults.contents = `${contents
      .replace(
        "  var window: UIWindow?",
        "  var window: UIWindow?\n  var initialLaunchOptions: [UIApplication.LaunchOptionsKey: Any]?",
      )
      .replace(startup, "    initialLaunchOptions = launchOptions")}
${fs.readFileSync(path.join(__dirname, "PostHogSceneDelegate.swift"), "utf8")}`;
    return cfg;
  });
};
