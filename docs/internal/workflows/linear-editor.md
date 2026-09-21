# Linear workflow editor

The linear editor reads from top to bottom.
It uses the existing `WORKFLOWS_LINEAR_VIEW` feature flag.
The graph layout and workflow execution do not change.

## Steps and colors

Step icons and colors come from `HogFlowSteps.tsx` in both editors.
The linear editor must not define a separate palette.
Step descriptions and setting previews wrap so that delay values, time windows, and time zones remain visible in a narrow panel.
Setting previews align to the right and share a row with the description when space permits.
Delay previews are hidden only when the step name already states the configured duration.

## Paths and shared steps

A branch group contains its paths and their steps.
Curved hierarchy lines connect sibling paths at each nesting level.
The line ends at the last path header, before any shared continuation.
Lines show the path hierarchy, not execution order between sibling paths.
Steps and continuation links do not have colored branch marks.
Step icons keep their existing colors.
Hover a path header, or focus one of its controls with the keyboard, to color its hierarchy lines.
The path background does not change.
The colored lines stop before the shared next step.
Nested headers color only their own lines, not the parent or sibling lines.
Hover and keyboard focus do not select a path or change its settings.
Conditional paths show their order and rule in a compact header, without a surrounding path box.
Expanded paths show their shared destination once, at the end of the path.
Continuation links keep the same spacing with and without hover.
Collapsed paths show their step count and destination below the header.
Condition labels use `If #1`, `If #2`, and so on to distinguish condition order from step numbers.
The first matching condition sets the path.
The condition settings explain this order instead of repeating the explanation at each nesting level.
The No match path stays visible when more conditions are hidden.
Wait steps distinguish a match from a timeout.
Random paths show their allocation percentages.

Each shared next step appears after the group that leads to it.
The existing tree builder determines this location from the workflow connections.
A shared next step does not wait for all paths to finish.
Paths without a shared next step keep their separate endings.
Collapsed paths still show their step count and destination.
Counts include nested steps, but do not include a shared step outside the path.

## Focus and insertion

Use **Focus on this path** in the path actions menu to show a path with multiple steps or nested branches at the full editor width.
The focused view shows its location and destination.
Use **Back to workflow** or the continuation button to return to the full workflow.
Focus changes only the view, not the stored workflow.

**Add step to [path]** inserts a step inside that path.
**Add step after [branch] paths** inserts a step before the shared continuation, using the existing join edges.
The regular controls between steps keep their insertion behavior.
Insertion controls appear on hover or keyboard focus and show their scope in a tooltip.
Empty paths keep a visible add button.

## Review checks

Compare simple sequences, a single branch, delays, time windows, wait outcomes, many conditions, and nested branches in Storybook.
Check the editor at 800px and 520px, including the settings panel and focused paths.
Check both light and dark themes.
Confirm that step colors match the graph editor, continuation links reach the correct step, and insertion controls modify the intended edges.
