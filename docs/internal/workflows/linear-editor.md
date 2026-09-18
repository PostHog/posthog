# Linear workflow editor

The linear editor reads from top to bottom.
It uses the existing `WORKFLOWS_LINEAR_VIEW` feature flag.
The graph editor and workflow execution do not change.

## Steps and colors

Step icons and colors come from `HogFlowSteps.tsx` in both editors.
The linear editor must not define a separate palette.
Step descriptions and setting previews wrap so that delay values, time windows, and time zones remain visible in a narrow panel.
Setting previews align to the right and share a row with the description when space permits.

## Paths and shared steps

A branch group contains its paths and their steps.
Conditional paths show their order, rule, step count, and destination.
Condition labels use `If #1`, `If #2`, and so on to distinguish condition order from step numbers.
The first matching condition sets the path.
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

Use **Focus on this path** to show a path with multiple steps or nested branches at the full editor width.
The focused view shows its location and destination.
Use **Back to workflow** or the continuation button to return to the full workflow.
Focus changes only the view, not the stored workflow.

**Add step to [path]** inserts a step inside that path.
**Add step after [branch] paths** inserts a step before the shared continuation, using the existing join edges.
The regular controls between steps keep their insertion behavior.

## Review checks

Compare simple sequences, a single branch, delays, time windows, wait outcomes, many conditions, and nested branches in Storybook.
Check the editor at 800px and 520px, including the settings panel and focused paths.
Check both light and dark themes.
Confirm that step colors match the graph editor, continuation links reach the correct step, and insertion controls modify the intended edges.
