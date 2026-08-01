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
    const navigationResult = electronApp.evaluate(
      async ({ BrowserWindow }, expectedUrl) => {
        const mainWindow = BrowserWindow.getAllWindows()[0];
        if (!mainWindow) throw new Error("Main window not found");

        return await new Promise<{
          defaultPrevented: boolean;
          isMainFrame: boolean;
        }>((resolve, reject) => {
          const timeout = setTimeout(() => {
            mainWindow.webContents.off("will-frame-navigate", listener);
            reject(new Error("Timed out waiting for subframe navigation"));
          }, 5000);
          const listener = (
            event: Electron.Event<Electron.WebContentsWillFrameNavigateEventParams>,
          ): void => {
            if (event.url !== expectedUrl) return;
            clearTimeout(timeout);
            mainWindow.webContents.off("will-frame-navigate", listener);
            resolve({
              defaultPrevented: event.defaultPrevented,
              isMainFrame: event.isMainFrame,
            });
          };
          mainWindow.webContents.on("will-frame-navigate", listener);
        });
      },
      targetUrl,
    );

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

    await expect(navigationResult).resolves.toEqual({
      defaultPrevented: true,
      isMainFrame: false,
    });
  });
});
