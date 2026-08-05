import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import {
  macOnlyNativeModules,
  requiredNativeModules,
  runtimeNativeModules,
  watcherPackageFor,
} from "../runtime-dependencies";

type BeforePackContext = {
  packager: { platform: { name: string } };
  arch: number;
};

function copyDep(
  name: string,
  rootNodeModules: string,
  localNodeModules: string,
): boolean {
  const src = path.join(rootNodeModules, name);
  if (!existsSync(src)) {
    const localSrc = path.join(localNodeModules, name);
    if (existsSync(localSrc)) {
      console.log(
        `[before-pack] "${name}" already in local node_modules, skipping`,
      );
      return true;
    }
    console.warn(
      `[before-pack] "${name}" not found in root or local node_modules, skipping`,
    );
    return false;
  }

  const dest = path.join(localNodeModules, name);
  const parentDir = path.dirname(dest);
  mkdirSync(parentDir, { recursive: true });
  rmSync(dest, { recursive: true, force: true });
  cpSync(src, dest, { recursive: true, dereference: true });
  console.log(`[before-pack] staged "${name}"`);
  return true;
}

function copyRequiredDep(
  name: string,
  rootNodeModules: string,
  localNodeModules: string,
): void {
  if (!copyDep(name, rootNodeModules, localNodeModules)) {
    throw new Error(
      `[before-pack] required native dependency "${name}" not found in node_modules`,
    );
  }
}

export default async function beforePack(context: BeforePackContext) {
  const platformName = context.packager.platform.name;
  const arch = context.arch;

  const rootNodeModules = path.resolve(__dirname, "../../../node_modules");
  const localNodeModules = path.resolve(__dirname, "../node_modules");

  console.log(`[before-pack] platform=${platformName} arch=${arch}`);
  console.log(`[before-pack] root node_modules: ${rootNodeModules}`);
  console.log(`[before-pack] local node_modules: ${localNodeModules}`);

  for (const dep of runtimeNativeModules) {
    if (requiredNativeModules.includes(dep)) {
      copyRequiredDep(dep, rootNodeModules, localNodeModules);
    } else {
      copyDep(dep, rootNodeModules, localNodeModules);
    }
  }

  const watcherPkg = watcherPackageFor(platformName, arch);
  if (watcherPkg) {
    copyRequiredDep(watcherPkg, rootNodeModules, localNodeModules);
  }

  if (platformName === "mac") {
    for (const dep of macOnlyNativeModules) {
      copyDep(dep, rootNodeModules, localNodeModules);
    }
  }

  const watcherBuild = path.join(localNodeModules, "@parcel/watcher/build");
  if (existsSync(watcherBuild)) {
    rmSync(watcherBuild, { recursive: true, force: true });
    console.log("[before-pack] removed @parcel/watcher/build");
  }
}
