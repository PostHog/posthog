import type { Plugin } from "vite";

const ENTRY_SCRIPT =
  /[ \t]*<script type="module"([^>]*?)\ssrc="([^"]+)"[^>]*><\/script>\n?/g;
const MODULE_PRELOAD = /[ \t]*<link rel="modulepreload"[^>]*>\n?/g;

function bootstrapScript(
  entries: { src: string; crossOrigin: boolean }[],
  preloads: string,
): string {
  return `    <script>
      (function () {
        var started = false;
        function start() {
          if (started) return;
          started = true;
          document.head.insertAdjacentHTML("beforeend", ${JSON.stringify(preloads)});
          for (var entry of ${JSON.stringify(entries)}) {
            var script = document.createElement("script");
            script.type = "module";
            if (entry.crossOrigin) script.crossOrigin = "";
            script.src = entry.src;
            document.head.appendChild(script);
          }
        }
        // A window that is still hidden gets no animation frames, so a timer backs the frames up.
        requestAnimationFrame(function () { requestAnimationFrame(start); });
        setTimeout(start, 500);
      })();
    </script>
`;
}

/**
 * Loads the renderer bundle after the first paint, so the boot shell in
 * index.html reaches the screen while the bundle still compiles. A module
 * script in the head is deferred but not asynchronous: the renderer compiles
 * and runs every module before it paints, which leaves the window empty for as
 * long as that takes.
 */
export function deferEntryUntilFirstPaint(html: string): string {
  const entries = [...html.matchAll(ENTRY_SCRIPT)].map((match) => ({
    src: match[2],
    crossOrigin: match[1].includes("crossorigin"),
  }));
  if (entries.length === 0) return html;

  const preloads = [...html.matchAll(MODULE_PRELOAD)]
    .map((match) => match[0].trim())
    .join("");

  return html
    .replace(ENTRY_SCRIPT, "")
    .replace(MODULE_PRELOAD, "")
    .replace("</body>", `${bootstrapScript(entries, preloads)}  </body>`);
}

export function firstPaintPlugin(): Plugin {
  return {
    name: "posthog-first-paint",
    apply: "build",
    transformIndexHtml: {
      order: "post",
      handler(html, ctx) {
        // Only the main window has a boot shell to paint; the quick-ask panels
        // open on demand and have nothing to show before their bundle runs.
        if (!ctx.path.endsWith("/index.html")) return html;
        return deferEntryUntilFirstPaint(html);
      },
    },
  };
}
