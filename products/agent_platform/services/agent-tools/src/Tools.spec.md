# Tools

Native `@posthog/*` tools the runner can dispatch, plus the intrinsic approval classification that floors how dangerous each one is allowed to be.

## invariants

- native-tool-approval-floor

## works when

- typechecks
- boundary "native-tool-approval-floor" at nativeToolApprovalClass via test "native tool authorization accessor"

## why

native-tool-approval-floor: whether a native tool needs human approval is an intrinsic property of the tool (mutating/external-effect vs read-only), not something each spec author must remember — a forgotten `requires_approval` flag used to dispatch mutating tools ungated. The class is now a REQUIRED field on every tool's definition (`NativeToolSchema.approval`), so `typechecks` makes an unclassified tool a compile error — totality enforced by the type system, not a parallel map plus a runtime test. `nativeToolApprovalClass` is the single read point: it returns each tool's co-located class and fails closed to `approve` on an id no tool declares; authors may tighten an individual ref via `requires_approval` but the resolver never loosens below the intrinsic class. The `via test` oracle iterates the live registry asserting the accessor never drifts from a tool's declared class (floored so an emptied registry can't pass vacuously).
