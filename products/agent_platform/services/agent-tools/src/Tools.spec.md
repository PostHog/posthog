# Tools

Native `@posthog/*` tools the runner can dispatch, plus the intrinsic approval classification that floors how dangerous each one is allowed to be.

## invariants

- native-tool-approval-floor

## works when

- typechecks
- boundary "native-tool-approval-floor" at NATIVE_TOOL_APPROVAL via test "native tool authorization totality"

## why

native-tool-approval-floor: whether a native tool needs human approval is an intrinsic property of the tool (mutating/external-effect vs read-only), not something each spec author must remember — a forgotten `requires_approval` flag used to dispatch mutating tools ungated. `NATIVE_TOOL_APPROVAL` classifies every registered tool, authors may tighten but never loosen the floor, and unknown ids fail closed to `approve`. The oracle enumerates the live tool registry and fails on any unclassified member or orphan classification, so adding a tool without deciding its class is a red build, not a silent `allow`.
