// @ts-expect-error jsdom ships no bundled types; only the test harness needs it
import { JSDOM } from "jsdom";
import { describe, expect, it } from "vitest";
import { injectArtifactHtmlCommentBridge } from "./artifactHtmlCommentBridge";
import { COMMENT_ACTION_BUTTON_THEMES } from "./selectionCommentAction";

const CHANNEL = "test-channel";
const BRIDGE_MARKER = "__POSTHOG_ARTIFACT_COMMENT_BRIDGE__";

function loadBridgeDocument(
  html: string,
  theme: "light" | "dark" = "light",
): JSDOM {
  const dom = new JSDOM(
    injectArtifactHtmlCommentBridge(html, { channel: CHANNEL, theme }),
    {
      runScripts: "dangerously",
      url: "https://localhost/",
    },
  );
  // jsdom collapses layout boxes to zero; the bridge hides the action for
  // zero-size ranges, which real documents never produce for text selections.
  dom.window.Range.prototype.getBoundingClientRect = () =>
    ({
      top: 40,
      left: 10,
      right: 110,
      bottom: 60,
      width: 100,
      height: 20,
    }) as DOMRect;
  dom.window.Range.prototype.getClientRects = function () {
    return [this.getBoundingClientRect()] as unknown as DOMRectList;
  };
  return dom;
}

function selectParagraph(dom: JSDOM): void {
  const selection = dom.window.getSelection();
  const paragraph = dom.window.document.querySelector("p");
  if (!selection || !paragraph) throw new Error("test document needs a <p>");
  const range = dom.window.document.createRange();
  range.selectNodeContents(paragraph);
  selection.addRange(range);
}

function pressOn(dom: JSDOM, selector: string): void {
  const element = dom.window.document.querySelector(selector);
  if (!element) throw new Error(`missing ${selector}`);
  element.dispatchEvent(
    new dom.window.MouseEvent("pointerdown", { bubbles: true }),
  );
}

function releaseOn(dom: JSDOM, selector: string): void {
  const element = dom.window.document.querySelector(selector);
  if (!element) throw new Error(`missing ${selector}`);
  element.dispatchEvent(
    new dom.window.MouseEvent("pointerup", { bubbles: true }),
  );
}

function actionButton(dom: JSDOM): HTMLElement | null {
  return dom.window.document.querySelector<HTMLElement>(
    ".ph-comment-action-button",
  );
}

describe("artifactHtmlCommentBridge", () => {
  it("shows the comment action only after the selection settles, not mid-drag", () => {
    const dom = loadBridgeDocument(
      "<html><body><p>some selectable text here</p></body></html>",
    );

    pressOn(dom, "p");
    selectParagraph(dom);
    dom.window.document.dispatchEvent(new dom.window.Event("selectionchange"));
    expect(actionButton(dom)?.style.display ?? "none").toBe("none");

    releaseOn(dom, "p");
    expect(actionButton(dom)?.style.display).toBe("flex");
    expect(actionButton(dom)?.textContent).toBe("Comment");
    // Anchored right of the selection end (110 + 8), centered on the end
    // line (50 - 14).
    expect(actionButton(dom)?.style.left).toBe("118px");
    expect(actionButton(dom)?.style.top).toBe("36px");
    dom.window.close();
  });

  it("ignores presses on the action button itself", () => {
    const dom = loadBridgeDocument(
      "<html><body><p>some selectable text here</p></body></html>",
    );

    pressOn(dom, "p");
    selectParagraph(dom);
    releaseOn(dom, "p");
    expect(actionButton(dom)?.style.display).toBe("flex");

    pressOn(dom, ".ph-comment-action-button");
    expect(actionButton(dom)?.style.display).toBe("flex");
    dom.window.close();
  });

  it("bakes the requested theme into the bridge styles", () => {
    const dark = injectArtifactHtmlCommentBridge("<html><body></body></html>", {
      channel: CHANNEL,
      theme: "dark",
    });
    const light = injectArtifactHtmlCommentBridge(
      "<html><body></body></html>",
      { channel: CHANNEL, theme: "light" },
    );
    expect(dark).toContain(
      `--ph-comment-action-bg:${COMMENT_ACTION_BUTTON_THEMES.dark.background}`,
    );
    expect(light).toContain(
      `--ph-comment-action-bg:${COMMENT_ACTION_BUTTON_THEMES.light.background}`,
    );
  });

  it("re-themes a running document from a host theme message", () => {
    const dom = loadBridgeDocument(
      "<html><body><p>text</p></body></html>",
      "light",
    );
    // jsdom's postMessage leaves event.source null; the bridge ignores those.
    dom.window.dispatchEvent(
      new dom.window.MessageEvent("message", {
        data: {
          marker: BRIDGE_MARKER,
          channel: CHANNEL,
          type: "theme",
          theme: "dark",
        },
        source: dom.window,
      }),
    );
    expect(
      dom.window.document.documentElement.style.getPropertyValue(
        "--ph-comment-action-bg",
      ),
    ).toBe(COMMENT_ACTION_BUTTON_THEMES.dark.background);
    dom.window.close();
  });
});
