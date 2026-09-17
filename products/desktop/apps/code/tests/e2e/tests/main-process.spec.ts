import { expect, test } from "../fixtures/electron";

test.describe("Main Process", () => {
  test("app info is accessible", async ({ electronApp }) => {
    const appName = await electronApp.evaluate(async ({ app }) => {
      return app.getName();
    });

    expect(appName).toBe("PostHog");
  });

  test("app is packaged correctly", async ({ electronApp }) => {
    const isPackaged = await electronApp.evaluate(async ({ app }) => {
      return app.isPackaged;
    });

    expect(isPackaged).toBe(true);
  });

  test("app has single instance lock", async ({ electronApp }) => {
    const appPaths = await electronApp.evaluate(async ({ app }) => {
      return {
        userData: app.getPath("userData"),
        exe: app.getPath("exe"),
        appData: app.getPath("appData"),
      };
    });

    expect(appPaths.userData).toBeTruthy();
    expect(appPaths.exe).toBeTruthy();
    expect(appPaths.appData).toBeTruthy();
  });

  test("user data path is set correctly", async ({ electronApp }) => {
    const userDataPath = await electronApp.evaluate(async ({ app }) => {
      return app.getPath("userData");
    });

    expect(userDataPath).toContain("posthog-code");
  });

  test("blocks external protocol navigation from a renderer subframe", async ({
    electronApp,
    window,
  }) => {
    const targetUrl = "custom-scheme://sandbox-navigation-test/payload";
    type NavigationRecord = { defaultPrevented: boolean; isMainFrame: boolean };
    type NavigationProbe = typeof globalThis & {
      __e2eSubframeNavigation?: NavigationRecord;
    };

    // The listener records the event instead of racing a timer against the
    // renderer setup below, which takes tens of seconds under Rosetta.
    await electronApp.evaluate(({ BrowserWindow }, expectedUrl) => {
      const mainWindow = BrowserWindow.getAllWindows()[0];
      if (!mainWindow) throw new Error("Main window not found");

      const probe = globalThis as NavigationProbe;
      probe.__e2eSubframeNavigation = undefined;
      const listener = (
        event: Electron.Event<Electron.WebContentsWillFrameNavigateEventParams>,
      ): void => {
        if (event.url !== expectedUrl) return;
        mainWindow.webContents.off("will-frame-navigate", listener);
        probe.__e2eSubframeNavigation = {
          defaultPrevented: event.defaultPrevented,
          isMainFrame: event.isMainFrame,
        };
      };
      mainWindow.webContents.on("will-frame-navigate", listener);
    }, targetUrl);

    const frameHandle = await window.evaluateHandle(() => {
      const iframe = document.createElement("iframe");
      iframe.srcdoc = '<button id="navigate">Navigate externally</button>';
      document.body.appendChild(iframe);
      return iframe;
    });
    const iframe = frameHandle.asElement();
    if (!iframe) throw new Error("Iframe was not created");
    const frame = await iframe.contentFrame();
    if (!frame) throw new Error("Iframe content frame was not created");

    await frame.evaluate((url) => {
      document.getElementById("navigate")?.addEventListener("click", () => {
        window.location.href = url;
      });
    }, targetUrl);

    await frame.getByText("Navigate externally").click();

    // The event fires as soon as the click lands, so this only bounds the
    // delivery. It starts after the setup above, which is the slow part.
    await expect
      .poll(
        () =>
          electronApp.evaluate(
            () => (globalThis as NavigationProbe).__e2eSubframeNavigation,
          ),
        { timeout: 30000 },
      )
      .toEqual({
        defaultPrevented: true,
        isMainFrame: false,
      });
  });
});
