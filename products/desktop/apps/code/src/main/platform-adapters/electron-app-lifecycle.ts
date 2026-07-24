import type { IAppLifecycle } from "@posthog/platform/app-lifecycle";
import { app } from "electron";
import { injectable } from "inversify";

@injectable()
export class ElectronAppLifecycle implements IAppLifecycle {
  public whenReady(): Promise<void> {
    return app.whenReady().then(() => undefined);
  }

  public quit(): void {
    app.quit();
  }

  public exit(code?: number): void {
    app.exit(code);
  }

  public onQuit(handler: () => void | Promise<void>): () => void {
    const listener = (event: Electron.Event) => {
      const result = handler();
      if (result instanceof Promise) {
        event.preventDefault();
        result.finally(() => app.quit());
      }
    };
    app.on("before-quit", listener);
    return () => app.off("before-quit", listener);
  }

  public registerDeepLinkScheme(scheme: string): void {
    app.setAsDefaultProtocolClient(scheme);
  }
}
