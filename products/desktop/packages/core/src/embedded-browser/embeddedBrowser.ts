import {
  EMBEDDED_BROWSER,
  type EmbeddedBrowserBounds,
  type EmbeddedBrowserEvent,
  type EmbeddedBrowserPageState,
  type IEmbeddedBrowser,
} from "@posthog/platform/embedded-browser";
import { inject, injectable } from "inversify";
import { normalizeBrowserUrl } from "./normalizeUrl";

export interface IEmbeddedBrowserService {
  open(input: {
    viewId: string;
    url: string;
    bounds: EmbeddedBrowserBounds;
  }): Promise<void>;
  navigate(viewId: string, url: string): Promise<void>;
  goBack(viewId: string): void;
  goForward(viewId: string): void;
  reload(viewId: string): void;
  setBounds(viewId: string, bounds: EmbeddedBrowserBounds): void;
  setVisible(viewId: string, visible: boolean): void;
  openDevTools(viewId: string): void;
  destroy(viewId: string): Promise<void>;
  getPageState(viewId: string): EmbeddedBrowserPageState | null;
  events(signal?: AbortSignal): AsyncIterable<EmbeddedBrowserEvent>;
}

/**
 * Policy layer over the host's embedded browser: every URL that reaches the
 * native view passes http(s) validation here, so no caller — UI, router, or
 * future automation — can point the view at file:, javascript:, or custom
 * schemes. The host adapter enforces the same rule for page-initiated
 * navigations (defense in depth).
 */
@injectable()
export class EmbeddedBrowserService implements IEmbeddedBrowserService {
  constructor(
    @inject(EMBEDDED_BROWSER) private readonly browser: IEmbeddedBrowser,
  ) {}

  async open(input: {
    viewId: string;
    url: string;
    bounds: EmbeddedBrowserBounds;
  }): Promise<void> {
    await this.browser.create({
      viewId: input.viewId,
      url: this.assertWebUrl(input.url),
      bounds: input.bounds,
    });
  }

  async navigate(viewId: string, url: string): Promise<void> {
    await this.browser.navigate(viewId, this.assertWebUrl(url));
  }

  goBack(viewId: string): void {
    this.browser.goBack(viewId);
  }

  goForward(viewId: string): void {
    this.browser.goForward(viewId);
  }

  reload(viewId: string): void {
    this.browser.reload(viewId);
  }

  setBounds(viewId: string, bounds: EmbeddedBrowserBounds): void {
    this.browser.setBounds(viewId, bounds);
  }

  setVisible(viewId: string, visible: boolean): void {
    this.browser.setVisible(viewId, visible);
  }

  openDevTools(viewId: string): void {
    this.browser.openDevTools(viewId);
  }

  async destroy(viewId: string): Promise<void> {
    await this.browser.destroy(viewId);
  }

  getPageState(viewId: string): EmbeddedBrowserPageState | null {
    return this.browser.getPageState(viewId);
  }

  events(signal?: AbortSignal): AsyncIterable<EmbeddedBrowserEvent> {
    return this.browser.events(signal);
  }

  private assertWebUrl(raw: string): string {
    const normalized = normalizeBrowserUrl(raw);
    if (!normalized) throw new Error(`Not a loadable web URL: ${raw}`);
    return normalized;
  }
}
