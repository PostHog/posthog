import { existsSync } from "node:fs";
import {
  type ElectronApplication,
  _electron as electron,
  expect,
  test,
} from "@playwright/test";
import {
  bumpChainFeed,
  CHAIN_FEED_DIR,
  CHAIN_RUN_FEED_DIR,
  FEED_DIR,
  isAppRunning,
  killApp,
  PRISTINE_APP,
  prepareChainFeed,
  prepareRunApp,
  RUN_APP,
  RUN_APP_BIN,
  RUN_DIR,
  readBundleVersion,
  readMainLog,
  resetShipItCache,
  runningAppExecutables,
  SHIPIT_DIR,
  shipItEvidence,
  startFeedServer,
  type UpdateProof,
  waitUntil,
  writeChainProof,
} from "../fixtures/update";

type UpdateStatus = {
  checking?: boolean;
  available?: boolean;
  availableVersion?: string;
  downloading?: boolean;
  downloadPercent?: number;
  updateReady?: boolean;
  version?: string;
};

// Installed on globalThis by main/index.ts when POSTHOG_E2E_UPDATE_FEED is set.
// The cast is erased at compile time, so the evaluate closures serialize to plain
// globalThis access in the main process.
type E2eHook = {
  check: () => void;
  periodicCheck: () => void;
  download: () => void;
  install: () => Promise<unknown>;
  status: () => UpdateStatus;
};
type Hooked = typeof globalThis & { __e2eUpdates: E2eHook };

const FEED_PORT = 8790;
const FEED_URL = `http://127.0.0.1:${FEED_PORT}`;
const OLD_VERSION = "1.0.0";
const MID_VERSION = "2.0.0";
// Must match CHAIN_VERSION in code-update-e2e.yml (feeds build-pair.sh).
const FINAL_VERSION = "3.0.0";

test.describe("macOS chained auto-update", () => {
  // Runs only via playwright.update-chain.config.ts; the general e2e suite
  // excludes update specs by path, so there is no env gate that could skip it.
  test.skip(process.platform !== "darwin", "macOS-only update flow");

  // The re-staging safety proof: with 2.0.0 already downloaded and staged by
  // Squirrel.Mac, a background check finds 3.0.0, downloads it, re-stages it
  // over the pending update and the restart lands directly on 3.0.0.
  test("re-stages a newer update over a staged one and relaunches into it", async () => {
    test.setTimeout(5 * 60_000);

    const proof: UpdateProof = {
      result: "FAIL",
      oldVersion: OLD_VERSION,
      newVersion: FINAL_VERSION,
      intermediateVersion: MID_VERSION,
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
      expect(
        existsSync(CHAIN_FEED_DIR),
        `missing chain feed at ${CHAIN_FEED_DIR}; run scripts/dev-update/build-pair.sh with CHAIN_VERSION=${FINAL_VERSION}`,
      ).toBe(true);

      prepareRunApp();
      prepareChainFeed();
      resetShipItCache();
      feed = startFeedServer(FEED_PORT, CHAIN_RUN_FEED_DIR);

      // Phase 1: stage the intermediate update on the old build.
      proof.failedStep = "launch";
      const launched = await electron.launch({
        executablePath: RUN_APP_BIN,
        args: [],
        env: {
          ...process.env,
          ELECTRON_DISABLE_GPU: "1",
          POSTHOG_E2E_UPDATE_FEED: FEED_URL,
        },
      });
      app = launched;

      await expect
        .poll(
          () =>
            launched.evaluate(() => typeof (globalThis as Hooked).__e2eUpdates),
          {
            timeout: 30_000,
            message: "update hook was never installed",
          },
        )
        .toBe("object");

      proof.failedStep = "start-version";
      const startVersion = await app.evaluate(({ app: a }) => a.getVersion());
      proof.bootedOn = startVersion;
      expect(startVersion, "run app should start on the old version").toBe(
        OLD_VERSION,
      );

      // The renderer syncs the "download updates automatically" setting (on by
      // default) shortly after boot, so each phase accepts both paths: manual
      // (available, then an explicit download) and auto (straight to
      // downloading/ready).
      proof.failedStep = "first-update-available";
      await app.evaluate(() => (globalThis as Hooked).__e2eUpdates.check());
      await pollStatus(
        app,
        (s) => offersVersion(s, MID_VERSION),
        "intermediate update never became available",
      );
      proof.feedAvailableVersion = MID_VERSION;

      proof.failedStep = "first-download";
      await downloadIfAvailable(app);
      await pollStatus(
        app,
        (s) => s.updateReady === true && s.version === MID_VERSION,
        "intermediate update never finished downloading",
      );
      proof.downloaded = true;

      // Wait for Squirrel to finish staging the intermediate update before
      // offering the next one. This mirrors real release cadence and keeps
      // the native updater idle when the replacement staging kicks off.
      proof.failedStep = "first-stage";
      await waitUntil(
        () => shipItEvidence().exists,
        120_000,
        "Squirrel never staged the intermediate update",
      );

      // Phase 2: bump the feed and prove the staged update is replaced.
      proof.failedStep = "feed-bump";
      bumpChainFeed();

      proof.failedStep = "second-update-available";
      await app.evaluate(() =>
        (globalThis as Hooked).__e2eUpdates.periodicCheck(),
      );
      await pollStatus(
        app,
        (s) => offersVersion(s, FINAL_VERSION),
        "newer update was never surfaced while one was staged",
      );

      proof.failedStep = "re-download";
      await downloadIfAvailable(app);
      await pollStatus(
        app,
        (s) => s.updateReady === true && s.version === FINAL_VERSION,
        "newer update never replaced the staged one",
      );
      proof.restagedVersion = FINAL_VERSION;

      // Phase 3: install and prove the swap lands on the final version, not
      // the intermediate one.
      proof.failedStep = "install-and-swap";
      const closed = app.waitForEvent("close");
      void app
        .evaluate(() => {
          void (globalThis as Hooked).__e2eUpdates.install();
        })
        .catch(() => undefined);
      await closed;

      await waitUntil(
        () => readBundleVersion(RUN_APP) === FINAL_VERSION,
        120_000,
        "bundle was not swapped to the final version",
      );
      proof.bundleVersionAfterSwap = readBundleVersion(RUN_APP);

      proof.failedStep = "auto-relaunch";
      await waitUntil(
        () => runningAppExecutables().some((exe) => exe.includes(RUN_DIR)),
        60_000,
        "Squirrel did not auto-relaunch the updated app",
      );
      proof.autoRelaunchedExecutable = runningAppExecutables().find((exe) =>
        exe.includes(RUN_DIR),
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
      expect(version).toBe(FINAL_VERSION);
      await updated.close();

      // Mechanism evidence: the second update was found by a background check
      // while one was staged, and Squirrel.Mac's ShipIt performed the swap.
      proof.failedStep = "evidence";
      const mainLog = readMainLog();
      expect(
        mainLog,
        "main.log missing the background-check-while-staged marker",
      ).toContain("background check while an update is available or staged");
      const shipIt = shipItEvidence();
      proof.shipItExists = shipIt.exists;
      proof.shipItEntries = shipIt.entries;
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
      writeChainProof(proof);
    }
  });
});

function offersVersion(status: UpdateStatus, version: string): boolean {
  if (status.updateReady === true) {
    return status.version === version;
  }
  return (
    (status.available === true || status.downloading === true) &&
    status.availableVersion === version
  );
}

async function downloadIfAvailable(app: ElectronApplication): Promise<void> {
  await app.evaluate(() => {
    const hook = (globalThis as Hooked).__e2eUpdates;
    if (hook.status().available === true) {
      hook.download();
    }
  });
}

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
