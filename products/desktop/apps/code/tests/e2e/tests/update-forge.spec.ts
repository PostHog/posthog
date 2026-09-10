import { existsSync } from "node:fs";
import {
  type ElectronApplication,
  _electron as electron,
  expect,
  test,
} from "@playwright/test";
import {
  FEED_DIR,
  FORGE_PRISTINE_APP,
  FORGE_RUN_APP,
  FORGE_RUN_APP_BIN,
  FORGE_RUN_APP_BIN_UPDATED,
  FORGE_RUN_APP_UPDATED,
  FORGE_RUN_DIR,
  isAppRunning,
  killApp,
  prepareForgeRunApp,
  readBundleVersion,
  readBundleVersionIfPresent,
  resetShipItCache,
  runningAppExecutables,
  SHIPIT_DIR,
  shipItEvidence,
  startFeedServer,
  type UpdateProof,
  waitUntil,
  writeForgeProof,
} from "../fixtures/update";

const FEED_PORT = 8789;
const FEED_URL = `http://127.0.0.1:${FEED_PORT}`;
const OLD_VERSION = "1.0.0";
const NEW_VERSION = "2.0.0";

// The "old" build here is a real Electron Forge release (v0.55.132), built by
// scripts/dev-update/build-old-forge.sh. It runs the genuine built-in Squirrel.Mac
// client (electron.autoUpdater) that shipped to users, not electron-updater. This
// proves a Forge build in the field auto-updates to the electron-builder build we
// ship now. The old build reaches the local feed via the POSTHOG_E2E_UPDATE_HOST
// env seam baked in at build time, so its own boot check drives the download.
test.describe("Forge -> electron-builder auto-update", () => {
  // Runs only via playwright.update-forge.config.ts; the general e2e suite
  // excludes update*.spec.ts by path, so there is no env gate that could
  // silently skip it.
  test.skip(process.platform !== "darwin", "macOS-only update flow");

  test("legacy Squirrel.Mac build updates to the electron-builder build", async () => {
    test.setTimeout(5 * 60_000);

    const proof: UpdateProof = {
      result: "FAIL",
      oldVersion: OLD_VERSION,
      newVersion: NEW_VERSION,
    };
    let feed: ReturnType<typeof startFeedServer> | undefined;
    let app: ElectronApplication | undefined;
    let updated: ElectronApplication | undefined;

    try {
      proof.failedStep = "preconditions";
      expect(
        existsSync(FORGE_PRISTINE_APP),
        `missing old Forge app at ${FORGE_PRISTINE_APP}; run scripts/dev-update/build-old-forge.sh`,
      ).toBe(true);
      expect(
        existsSync(FEED_DIR),
        `missing feed at ${FEED_DIR}; run scripts/dev-update/build-pair.sh`,
      ).toBe(true);

      killApp();
      // Isolate the ShipIt evidence from the baseline leg, which swaps the same
      // bundle id earlier in the same CI job.
      resetShipItCache();
      prepareForgeRunApp();
      feed = startFeedServer(FEED_PORT);

      // Phase 1: launch the old Forge build pointed at the local feed and let its
      // own updater drive the real check + download.
      proof.failedStep = "launch";
      app = await electron.launch({
        executablePath: FORGE_RUN_APP_BIN,
        args: [],
        env: {
          ...process.env,
          ELECTRON_DISABLE_GPU: "1",
          POSTHOG_E2E_UPDATE_HOST: FEED_URL,
        },
      });

      // Prove we actually start on the old Forge version, so the swap is real.
      proof.failedStep = "start-version";
      const startVersion = await app.evaluate(({ app: a }) => a.getVersion());
      proof.bootedOn = startVersion;
      expect(startVersion, "old app should boot on the Forge version").toBe(
        OLD_VERSION,
      );

      // Wait for the genuine built-in Squirrel.Mac client to download the update.
      // The app's UpdatesService checks on boot (against our local feed) and the
      // built-in autoUpdater auto-downloads, so update-downloaded fires without a
      // separate download step. We only observe it.
      proof.failedStep = "download";
      const downloadedName = await app.evaluate(
        ({ autoUpdater }) =>
          new Promise<string>((resolve, reject) => {
            const timer = setTimeout(
              () =>
                reject(
                  new Error(
                    "built-in autoUpdater did not download an update within 180s",
                  ),
                ),
              180_000,
            );
            autoUpdater.on("error", (err) => {
              clearTimeout(timer);
              reject(err);
            });
            autoUpdater.on(
              "update-downloaded",
              (_event, _releaseNotes, releaseName) => {
                clearTimeout(timer);
                resolve(releaseName ?? "");
              },
            );
          }),
      );
      proof.feedAvailableVersion = downloadedName || NEW_VERSION;
      proof.downloaded = true;
      console.log(`Squirrel.Mac downloaded: ${downloadedName}`);

      // Drive the install on the genuine client and wait for it to quit.
      proof.failedStep = "install-and-swap";
      const closed = app.waitForEvent("close");
      void app
        .evaluate(({ autoUpdater }) => autoUpdater.quitAndInstall())
        .catch(() => undefined);
      await closed;

      // Phase 2: prove the swap, which installs under the update's own bundle name (a rename on disk).
      await waitUntil(
        () => readBundleVersionIfPresent(FORGE_RUN_APP_UPDATED) === NEW_VERSION,
        120_000,
        "bundle was not swapped to the renamed new version",
      );
      proof.bundleVersionAfterSwap = readBundleVersion(FORGE_RUN_APP_UPDATED);
      expect(
        existsSync(FORGE_RUN_APP),
        "old-named bundle should be gone after the renaming swap",
      ).toBe(false);

      // Squirrel's relaunch helper lived in the removed old-named bundle, so record the outcome without asserting auto-relaunch.
      proof.autoRelaunchedExecutable = runningAppExecutables().find((exe) =>
        exe.includes(FORGE_RUN_DIR),
      );
      console.log(
        `Post-swap running executable: ${proof.autoRelaunchedExecutable ?? "none (no auto-relaunch across the rename)"}`,
      );

      killApp();
      await waitUntil(
        () => !isAppRunning(),
        30_000,
        "app instance did not exit",
      );

      proof.failedStep = "fresh-launch";
      updated = await electron.launch({
        executablePath: FORGE_RUN_APP_BIN_UPDATED,
        args: [],
        env: { ...process.env, ELECTRON_DISABLE_GPU: "1" },
      });
      const version = await updated.evaluate(({ app: a }) => a.getVersion());
      proof.freshLaunchVersion = version;
      expect(version).toBe(NEW_VERSION);
      await updated.close();

      // Mechanism evidence: Squirrel.Mac's ShipIt is what performed the in-place
      // swap, so its cache is direct proof the genuine client did the install.
      proof.failedStep = "evidence";
      const shipIt = shipItEvidence();
      proof.shipItExists = shipIt.exists;
      proof.shipItEntries = shipIt.entries;
      console.log(
        `Squirrel ShipIt cache: exists=${shipIt.exists} entries=[${shipIt.entries.join(", ")}]`,
      );
      expect(
        shipIt.exists,
        `no Squirrel ShipIt cache at ${SHIPIT_DIR}; the swap was not performed by Squirrel`,
      ).toBe(true);

      proof.failedStep = undefined;
      proof.result = "PASS";
    } catch (err) {
      proof.error = err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      await app?.close().catch(() => {});
      await updated?.close().catch(() => {});
      feed?.kill();
      killApp();
      proof.finishedAt = new Date().toISOString();
      writeForgeProof(proof);
    }
  });
});
