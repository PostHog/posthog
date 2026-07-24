import { existsSync } from "node:fs";
import {
  type ElectronApplication,
  _electron as electron,
  expect,
  test,
} from "@playwright/test";
import {
  FEED_DIR,
  isAppRunning,
  killApp,
  PRISTINE_APP,
  prepareRunApp,
  RUN_APP,
  RUN_APP_BIN,
  RUN_DIR,
  readBundleVersion,
  readMainLog,
  runningAppExecutables,
  SHIPIT_DIR,
  shipItEvidence,
  startFeedServer,
  type UpdateProof,
  waitUntil,
  writeProof,
} from "../fixtures/update";

type UpdateStatus = {
  checking?: boolean;
  available?: boolean;
  availableVersion?: string;
  downloading?: boolean;
  downloadPercent?: number;
  updateReady?: boolean;
};

// Installed on globalThis by main/index.ts when POSTHOG_E2E_UPDATE_FEED is set.
// The cast is erased at compile time, so the evaluate closures serialize to plain
// globalThis access in the main process.
type E2eHook = {
  check: () => void;
  download: () => void;
  install: () => Promise<unknown>;
  status: () => UpdateStatus;
};
type Hooked = typeof globalThis & { __e2eUpdates: E2eHook };

const FEED_PORT = 8788;
const FEED_URL = `http://127.0.0.1:${FEED_PORT}`;
const OLD_VERSION = "1.0.0";
const NEW_VERSION = "2.0.0";

test.describe("macOS auto-update", () => {
  // Runs only via playwright.update.config.ts; the general e2e suite excludes
  // this file by path, so there is no env gate that could silently skip it.
  test.skip(process.platform !== "darwin", "macOS-only update flow");

  test("downloads, installs and relaunches into the new version", async () => {
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
        existsSync(PRISTINE_APP),
        `missing built app at ${PRISTINE_APP}; run scripts/dev-update/build-pair.sh`,
      ).toBe(true);
      expect(
        existsSync(FEED_DIR),
        `missing feed at ${FEED_DIR}; run scripts/dev-update/build-pair.sh`,
      ).toBe(true);

      prepareRunApp();
      feed = startFeedServer(FEED_PORT);

      // Phase 1: drive the real download + install on the old build.
      proof.failedStep = "launch";
      app = await electron.launch({
        executablePath: RUN_APP_BIN,
        args: [],
        env: {
          ...process.env,
          ELECTRON_DISABLE_GPU: "1",
          POSTHOG_E2E_UPDATE_FEED: FEED_URL,
        },
      });

      await expect
        .poll(
          () => app.evaluate(() => typeof (globalThis as Hooked).__e2eUpdates),
          {
            timeout: 30_000,
            message: "update hook was never installed",
          },
        )
        .toBe("object");

      // Prove we actually start on the old version, so the swap is real.
      proof.failedStep = "start-version";
      const startVersion = await app.evaluate(({ app: a }) => a.getVersion());
      proof.bootedOn = startVersion;
      expect(startVersion, "run app should start on the old version").toBe(
        OLD_VERSION,
      );

      proof.failedStep = "update-available";
      await app.evaluate(() => (globalThis as Hooked).__e2eUpdates.check());
      await pollStatus(
        app,
        (s) => s.available === true && s.availableVersion === NEW_VERSION,
        "update never became available",
      );
      proof.feedAvailableVersion = NEW_VERSION;

      proof.failedStep = "download";
      await app.evaluate(() => (globalThis as Hooked).__e2eUpdates.download());
      await pollStatus(
        app,
        (s) => s.updateReady === true,
        "update never finished downloading",
      );
      proof.downloaded = true;

      proof.failedStep = "install-and-swap";
      const closed = app.waitForEvent("close");
      void app
        .evaluate(() => {
          void (globalThis as Hooked).__e2eUpdates.install();
        })
        .catch(() => undefined);
      await closed;

      // Phase 2: prove the bundle swapped and a fresh launch is the new version.
      await waitUntil(
        () => readBundleVersion(RUN_APP) === NEW_VERSION,
        120_000,
        "bundle was not swapped to the new version",
      );
      proof.bundleVersionAfterSwap = readBundleVersion(RUN_APP);

      // Squirrel relaunches the installed app (isForceRunAfter=true); confirm the
      // auto-relaunched process actually came up running from the swapped bundle.
      proof.failedStep = "auto-relaunch";
      await waitUntil(
        () => runningAppExecutables().some((exe) => exe.includes(RUN_DIR)),
        60_000,
        "Squirrel did not auto-relaunch the updated app",
      );
      proof.autoRelaunchedExecutable = runningAppExecutables().find((exe) =>
        exe.includes(RUN_DIR),
      );
      console.log(
        `Auto-relaunched from swapped bundle: ${proof.autoRelaunchedExecutable}`,
      );

      killApp();
      await waitUntil(
        () => !isAppRunning(),
        30_000,
        "relaunched instance did not exit",
      );

      proof.failedStep = "fresh-launch";
      updated = await electron.launch({
        executablePath: RUN_APP_BIN,
        args: [],
        env: { ...process.env, ELECTRON_DISABLE_GPU: "1" },
      });
      const version = await updated.evaluate(({ app: a }) => a.getVersion());
      proof.freshLaunchVersion = version;
      expect(version).toBe(NEW_VERSION);
      await updated.close();

      // Mechanism evidence: our updater drove a real download and install, and
      // Squirrel.Mac's ShipIt is what performed the in-place swap.
      proof.failedStep = "evidence";
      const mainLog = readMainLog();
      expect(
        mainLog,
        "main.log missing the completed-download marker",
      ).toContain("Update downloaded, awaiting user confirmation");
      expect(mainLog, "main.log missing the install marker").toContain(
        "Installing update and restarting",
      );
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
      writeProof(proof);
    }
  });
});

async function pollStatus(
  app: ElectronApplication,
  predicate: (status: UpdateStatus) => boolean,
  message: string,
): Promise<void> {
  await expect
    .poll(
      async () =>
        predicate(
          await app.evaluate(() =>
            (globalThis as Hooked).__e2eUpdates.status(),
          ),
        ),
      { timeout: 120_000, message },
    )
    .toBe(true);
}
