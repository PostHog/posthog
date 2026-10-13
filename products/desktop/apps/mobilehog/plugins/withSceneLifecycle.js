// Xcode 27's SDK refuses to launch apps that do not adopt the UIScene life
// cycle. Expo 57.0.23 ships `ExpoAppSceneDelegate` but no plugin release yet,
// so this mirrors @config-plugins/expo-uiscene-lifecycle: the AppDelegate
// exposes its factory and the scene delegate creates the window.
const { withDangerousMod, withInfoPlist } = require("@expo/config-plugins");
const fs = require("node:fs");
const path = require("node:path");

const CLASS_LINE = "class AppDelegate: ExpoAppDelegate {";
const SCENE_CLASS_LINE =
  "class AppDelegate: ExpoAppDelegate, ExpoReactNativeFactoryProvider {";

function patchAppDelegate(source) {
  if (source.includes(SCENE_CLASS_LINE)) return source;
  if (!source.includes(CLASS_LINE)) {
    throw new Error(
      "withSceneLifecycle: AppDelegate.swift is not the Expo 57 template",
    );
  }
  let out = source.replace(CLASS_LINE, SCENE_CLASS_LINE);
  out = out.replace(
    /\n\s*window = UIWindow\(frame: UIScreen\.main\.bounds\)\n/,
    "\n",
  );
  out = out.replace(
    /\n\s*factory\.startReactNative\(\s*withModuleName: "main",\s*in: window,\s*launchOptions: launchOptions\)\n/,
    "\n",
  );
  if (out.includes("startReactNative(")) {
    throw new Error(
      "withSceneLifecycle: could not remove the AppDelegate React Native start",
    );
  }
  return out;
}

module.exports = function withSceneLifecycle(config) {
  config = withInfoPlist(config, (mod) => {
    mod.modResults.UIApplicationSceneManifest = {
      UIApplicationSupportsMultipleScenes: false,
      UISceneConfigurations: {
        UIWindowSceneSessionRoleApplication: [
          {
            UISceneConfigurationName: "Default Configuration",
            UISceneDelegateClassName: "EXExpoAppSceneDelegate",
          },
        ],
      },
    };
    return mod;
  });

  return withDangerousMod(config, [
    "ios",
    (mod) => {
      const file = path.join(
        mod.modRequest.platformProjectRoot,
        mod.modRequest.projectName,
        "AppDelegate.swift",
      );
      fs.writeFileSync(file, patchAppDelegate(fs.readFileSync(file, "utf8")));
      return mod;
    },
  ]);
};
