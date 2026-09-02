import type {
  ExtensionAPI,
  ExtensionContext,
  SessionInfoChangedEvent,
  SessionStartEvent,
  Theme,
} from "@earendil-works/pi-coding-agent";
import { initTheme } from "@earendil-works/pi-coding-agent";
import { describe, expect, it, vi } from "vitest";
import { createHogBrandingExtension } from "./extension";

// `keyHint`/`keyText`/`rawKeyHint` read the app's active keybindings and
// current theme through internal singletons initialized by the TUI runtime
// before `session_start` fires. Initialize it here so the header factory can
// be exercised outside of a running TUI session.
initTheme();

function fakeTheme(): Theme {
  return {
    fg: (_color: string, text: string) => text,
    bold: (text: string) => text,
  } as unknown as Theme;
}

type Handler<E> = (event: E, ctx: ExtensionContext) => void | Promise<void>;

function fakePi() {
  const handlers = {
    session_start: [] as Array<Handler<SessionStartEvent>>,
    session_info_changed: [] as Array<Handler<SessionInfoChangedEvent>>,
  };
  const pi = {
    on: vi.fn((eventName: string, handler: never) => {
      if (eventName === "session_start") {
        handlers.session_start.push(handler as never);
      }
      if (eventName === "session_info_changed") {
        handlers.session_info_changed.push(handler as never);
      }
    }),
  } as unknown as ExtensionAPI;
  return { pi, handlers };
}

function fakeCtx(options: {
  mode?: "tui" | "rpc" | "json" | "print";
  cwd?: string;
  sessionName?: string;
  setHeader?: (factory: unknown) => void;
  setTitle?: (title: string) => void;
}): ExtensionContext {
  return {
    mode: options.mode ?? "tui",
    ui: {
      setHeader: options.setHeader ?? vi.fn(),
      setTitle: options.setTitle ?? vi.fn(),
    },
    sessionManager: {
      getCwd: () => options.cwd ?? "/home/user/my-project",
      getSessionName: () => options.sessionName,
    },
  } as unknown as ExtensionContext;
}

describe("createHogBrandingExtension", () => {
  it("registers a session_start handler that sets a custom header in TUI mode", async () => {
    const { pi, handlers } = fakePi();
    const setHeader = vi.fn();

    const extension = createHogBrandingExtension({ version: "9.9.9" });
    await extension(pi);

    expect(pi.on).toHaveBeenCalledWith("session_start", expect.any(Function));

    const ctx = fakeCtx({ mode: "tui", setHeader });
    await handlers.session_start[0]?.({} as SessionStartEvent, ctx);

    expect(setHeader).toHaveBeenCalledTimes(1);
    const factory = setHeader.mock.calls[0]?.[0];
    const component = factory(undefined, fakeTheme());
    const lines = component.render(80);

    expect(lines[0]).toContain("Hog");
    expect(lines[0]).toContain("A Pi distribution by PostHog");
    expect(lines[0]).toContain("v9.9.9");
  });

  it("does not set a header outside TUI mode", async () => {
    const { pi, handlers } = fakePi();
    const setHeader = vi.fn();

    const extension = createHogBrandingExtension();
    await extension(pi);

    const ctx = fakeCtx({ mode: "print", setHeader });
    await handlers.session_start[0]?.({} as SessionStartEvent, ctx);

    expect(setHeader).not.toHaveBeenCalled();
  });

  it("toggles between compact and expanded instructions via setExpanded", async () => {
    const { pi, handlers } = fakePi();
    const setHeader = vi.fn();

    const extension = createHogBrandingExtension();
    await extension(pi);

    const ctx = fakeCtx({ mode: "tui", setHeader });
    await handlers.session_start[0]?.({} as SessionStartEvent, ctx);

    const factory = setHeader.mock.calls[0]?.[0];
    const component = factory(undefined, fakeTheme());

    const compactLines = component.render(80);
    component.setExpanded(true);
    const expandedLines = component.render(80);

    expect(expandedLines.length).not.toEqual(compactLines.length);
  });

  it("never returns a rendered line containing an embedded newline (compact or expanded)", async () => {
    // Regression test: `render()` must return one terminal line per array
    // entry. A previous version joined the expanded hint list into a single
    // "\n"-separated string and returned it as one array entry, which made
    // the TUI measure the whole multi-line block as one line and crash with
    // "Rendered line N exceeds terminal width".
    const { pi, handlers } = fakePi();
    const setHeader = vi.fn();

    const extension = createHogBrandingExtension();
    await extension(pi);

    const ctx = fakeCtx({ mode: "tui", setHeader });
    await handlers.session_start[0]?.({} as SessionStartEvent, ctx);

    const factory = setHeader.mock.calls[0]?.[0];
    const component = factory(undefined, fakeTheme());

    for (const line of component.render(80)) {
      expect(line).not.toContain("\n");
    }
    component.setExpanded(true);
    for (const line of component.render(80)) {
      expect(line).not.toContain("\n");
    }
  });

  it("sets a Hog-branded terminal title on session_start, with and without a session name", async () => {
    const { pi, handlers } = fakePi();

    const extension = createHogBrandingExtension();
    await extension(pi);

    const setTitleNoName = vi.fn();
    await handlers.session_start[0]?.(
      {} as SessionStartEvent,
      fakeCtx({ cwd: "/home/user/my-project", setTitle: setTitleNoName }),
    );
    expect(setTitleNoName).toHaveBeenCalledWith("hog - my-project");

    const setTitleWithName = vi.fn();
    await handlers.session_start[0]?.(
      {} as SessionStartEvent,
      fakeCtx({
        cwd: "/home/user/my-project",
        sessionName: "fix-bug",
        setTitle: setTitleWithName,
      }),
    );
    expect(setTitleWithName).toHaveBeenCalledWith("hog - fix-bug - my-project");
  });

  it("updates the terminal title on session_info_changed", async () => {
    const { pi, handlers } = fakePi();

    const extension = createHogBrandingExtension();
    await extension(pi);

    expect(pi.on).toHaveBeenCalledWith(
      "session_info_changed",
      expect.any(Function),
    );

    const setTitle = vi.fn();
    await handlers.session_info_changed[0]?.(
      {
        type: "session_info_changed",
        name: "renamed",
      } as SessionInfoChangedEvent,
      fakeCtx({
        cwd: "/home/user/my-project",
        sessionName: "renamed",
        setTitle,
      }),
    );

    expect(setTitle).toHaveBeenCalledWith("hog - renamed - my-project");
  });

  it("re-applies the branded title on the next tick to win the race against pi's own updateTerminalTitle()", async () => {
    vi.useFakeTimers();
    try {
      const { pi, handlers } = fakePi();
      const extension = createHogBrandingExtension();
      await extension(pi);

      const setTitle = vi.fn();
      const ctx = fakeCtx({ cwd: "/home/user/my-project", setTitle });
      await handlers.session_start[0]?.({} as SessionStartEvent, ctx);

      // Set immediately...
      expect(setTitle).toHaveBeenCalledTimes(1);
      expect(setTitle).toHaveBeenLastCalledWith("hog - my-project");

      // Simulate pi's own interactive-mode stomping the title synchronously
      // right after our handler resolves, as it does in practice.
      setTitle("\u03c0 - my-project");
      expect(setTitle).toHaveBeenLastCalledWith("\u03c0 - my-project");

      // ...and re-applied on the next tick, winning the race.
      vi.runAllTimers();
      expect(setTitle).toHaveBeenLastCalledWith("hog - my-project");
    } finally {
      vi.useRealTimers();
    }
  });
});
