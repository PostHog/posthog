import {
  emptySketchpadSnapshot,
  SKETCHPAD_ADD_FRAGMENT_TOOL_NAME,
  SKETCHPAD_UPDATE_FRAGMENT_TOOL_NAME,
} from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { toolCallToOp } from "./toolCalls";

describe("toolCallToOp", () => {
  const code = "export default function Card() { return null }";

  it("carries the fragment's declared capabilities onto the board", () => {
    const op = toolCallToOp(
      SKETCHPAD_ADD_FRAGMENT_TOOL_NAME,
      { id: "kpi", code, capabilities: { inlineQueries: true } },
      emptySketchpadSnapshot(),
    );

    expect(op).toMatchObject({
      type: "add_fragment",
      fragment: {
        capabilities: { inlineQueries: true, insights: [], state: [] },
      },
    });
  });

  it("declares nothing for a fragment that asks for nothing", () => {
    const op = toolCallToOp(
      SKETCHPAD_ADD_FRAGMENT_TOOL_NAME,
      { id: "kpi", code },
      emptySketchpadSnapshot(),
    );

    expect(op).toMatchObject({
      fragment: { capabilities: { inlineQueries: false, insights: [], state: [] } },
    });
  });

  it("updates what an existing fragment may reach", () => {
    const op = toolCallToOp(
      SKETCHPAD_UPDATE_FRAGMENT_TOOL_NAME,
      { id: "kpi", patch: { capabilities: { state: ["shared"] } } },
      emptySketchpadSnapshot(),
    );

    expect(op).toMatchObject({
      type: "update_fragment",
      patch: { capabilities: { inlineQueries: false, insights: [], state: ["shared"] } },
    });
  });
});
