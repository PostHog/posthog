# Loop

The session turn loop: model streaming, tool dispatch, and the approval gate that decides whether a tool call executes now or queues for a human decision.

## invariants

- gated-dispatch-single-path

## works when

- typechecks
- boundary "gated-dispatch-single-path" at gateTool via test "gate chokepoint"

## why

gated-dispatch-single-path: whether a gated tool call may execute is decided in exactly one place. Every tool lane (native, custom, MCP inline, MCP proxy, client, synthetic helpers) is wrapped through `gateTool`, which stamps a module-private brand; `assertToolsGated` runs before tools reach the model loop and throws on any unbranded tool, so a lane that skips the gate is a loud boot-time failure instead of a silent fail-open — the shape behind repeated production fixes where one wrap site was forgotten while the others were patched. The oracle enumerates every approval authority in `ApprovalTypeSchema.options` (floored, so an emptied enum can't pass vacuously) and asserts a gated call never reaches the real executor without a decision row, plus that an unbranded tool injected into dispatch throws.
