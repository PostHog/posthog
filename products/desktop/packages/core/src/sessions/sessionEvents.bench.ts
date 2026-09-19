import type { StoredLogEntry } from "@posthog/shared";
import { bench, describe } from "vitest";
import { convertStoredEntriesToEvents } from "./sessionEvents";

// Not run in CI (test globs only match *.test.*). Reproduce with:
//   cd packages/core && pnpm vitest bench src/sessions/sessionEvents.bench.ts

/**
 * A session log shaped like the residency fixtures: per turn a user message,
 * tool calls with completion updates, and a stream of assistant chunks. This
 * is the store-side work a task flip re-pays after its transcript was
 * evicted: JSON.parse per log line plus the event conversion (the UI-side
 * rebuild on top of it is benchmarked in packages/ui).
 */
function makeRawLog(turns: number): string {
  const lines: string[] = [];
  const chunk =
    "Tracing how eviction schedules interact with the residency grace period and the rehydration path. ";
  const push = (update: unknown) => {
    lines.push(
      JSON.stringify({
        type: "notification",
        timestamp: new Date(2026, 0, 1).toISOString(),
        notification: {
          jsonrpc: "2.0",
          method: "session/update",
          params: { sessionId: "run-bench", update },
        },
      }),
    );
  };
  for (let t = 0; t < turns; t++) {
    push({
      sessionUpdate: "user_message",
      content: { type: "text", text: `prompt ${t}: ${chunk}` },
    });
    for (let k = 0; k < 4; k++) {
      const toolCallId = `turn${t}-tool${k}`;
      push({
        sessionUpdate: "tool_call",
        toolCallId,
        kind: "execute",
        status: "pending",
        title: `Run step ${k} of turn ${t}`,
        rawInput: { command: `pnpm vitest run suite-${t}-${k}`, cwd: "/repo" },
      });
      push({
        sessionUpdate: "tool_call_update",
        toolCallId,
        status: "completed",
        rawOutput: chunk.repeat(8),
      });
    }
    for (let c = 0; c < 20; c++) {
      push({
        sessionUpdate: "agent_message_chunk",
        content: { type: "text", text: chunk },
      });
    }
  }
  return `${lines.join("\n")}\n`;
}

for (const turns of [100, 1000]) {
  const raw = makeRawLog(turns);
  const lineCount = turns * 29;
  describe(`rehydrate after eviction, ${lineCount} log lines`, () => {
    bench("JSON.parse per line + convertStoredEntriesToEvents", () => {
      const entries: StoredLogEntry[] = [];
      for (const line of raw.split("\n")) {
        if (!line) continue;
        entries.push(JSON.parse(line));
      }
      convertStoredEntriesToEvents(entries);
    });
  });
}
