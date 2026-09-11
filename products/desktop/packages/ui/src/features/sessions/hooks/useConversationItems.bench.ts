import type { AcpMessage } from "@posthog/shared";
import { renderHook } from "@testing-library/react";
import { bench, describe } from "vitest";
import type { ConversationPersistKey } from "./conversationDerivedCache";
import { useConversationItems } from "./useConversationItems";

// Not run in CI (test globs only match *.test.*). Reproduce with:
//   cd packages/ui && pnpm vitest bench src/features/sessions/hooks/useConversationItems.bench.ts

function updateMsg(ts: number, update: unknown): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: { jsonrpc: "2.0", method: "session/update", params: { update } },
  };
}

/**
 * A transcript shaped like a real agent session: per turn one user prompt,
 * a few tool calls with completion updates, a stream of assistant chunks,
 * and the prompt response. 30 events per turn.
 */
function makeTranscript(turns: number): AcpMessage[] {
  const events: AcpMessage[] = [];
  let ts = 0;
  const chunk =
    "Reading the session service to trace how eviction schedules interact " +
    "with the residency grace period and the rehydration path. ";
  for (let t = 0; t < turns; t++) {
    events.push({
      type: "acp_message",
      ts: ts++,
      message: {
        jsonrpc: "2.0",
        id: t + 1,
        method: "session/prompt",
        params: { prompt: [{ type: "text", text: `prompt ${t}: ${chunk}` }] },
      },
    });
    for (let k = 0; k < 4; k++) {
      const toolCallId = `turn${t}-tool${k}`;
      events.push(
        updateMsg(ts++, {
          sessionUpdate: "tool_call",
          toolCallId,
          kind: "execute",
          status: "pending",
          title: `Run step ${k} of turn ${t}`,
          rawInput: {
            command: `pnpm vitest run suite-${t}-${k}`,
            cwd: "/repo",
          },
        }),
      );
      events.push(
        updateMsg(ts++, {
          sessionUpdate: "tool_call_update",
          toolCallId,
          status: "completed",
          rawOutput: chunk.repeat(8),
        }),
      );
    }
    for (let c = 0; c < 20; c++) {
      events.push(
        updateMsg(ts++, {
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text: chunk },
        }),
      );
    }
    events.push({
      type: "acp_message",
      ts: ts++,
      message: {
        jsonrpc: "2.0",
        id: t + 1,
        result: { stopReason: "end_turn" },
      },
    });
  }
  return events;
}

for (const turns of [100, 1000]) {
  const events = makeTranscript(turns);
  describe(`task re-open, ${events.length} events`, () => {
    const key: ConversationPersistKey = {
      scope: "chat-thread",
      taskId: `bench-${turns}`,
    };

    // Pre-PR behavior: the builder dies with the component, so every re-open
    // re-parses the whole transcript.
    bench("without persist key (every re-open re-parses)", () => {
      const hook = renderHook(() => useConversationItems(events, false));
      hook.unmount();
    });

    // This PR: the first open parses, every later re-open hits the module
    // cache and returns the memoized result identity.
    bench("with persist key (warm re-open)", () => {
      const hook = renderHook(() =>
        useConversationItems(events, false, undefined, key),
      );
      hook.unmount();
    });
  });
}
