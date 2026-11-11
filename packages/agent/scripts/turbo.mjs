import { spawnSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import {
  targetArch,
  targetPlatform,
} from "../packages/agent/build/native-binary.mjs";

writeFileSync(
  new URL("../.platform-stamp", import.meta.url),
  `${targetPlatform()}-${targetArch()}\n`,
);

const turbo = createRequire(import.meta.url).resolve("turbo/bin/turbo");
const result = spawnSync(process.execPath, [turbo, ...process.argv.slice(2)], {
  stdio: "inherit",
});
process.exit(result.status ?? 1);
