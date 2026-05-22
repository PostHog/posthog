# Test Case Design

Routes are where frontend QA runs. Test cases come from the behavior the diff
could change.

For each meaningful hunk, ask:

- What user-visible behavior could this alter?
- What can a reviewer learn only by running the UI?
- What is the smallest workflow that proves the behavior?
- What state, data, feature flag, viewport, or theme makes the risk visible?
- What would be the clearest evidence if this regressed?

## Case Shape

Use this shape in `run-notes.md` and `findings.json` planning notes:

```json
{
  "kind": "browser|visual|coverage_gap",
  "changed_behavior": "Saving a dashboard filter should preserve the breakdown",
  "risk": "Regression silently drops user filter state after save",
  "setup": "Use a dashboard with an insight and a breakdown",
  "route": "/dashboard/:id",
  "action": "Change filter, save, reload dashboard",
  "expected": "Filter and breakdown remain visible after reload",
  "evidence": "Screenshot after reload plus console/network check"
}
```

`changed_behavior` and `risk` should be human-readable. Avoid file-only plans
like "open Dashboard.tsx route". Tie the case to what could break for a user.

## Priority Order

Choose cases in this order:

1. Bug reproduction or a changed save, submit, delete, duplicate, invite, create,
   or navigation flow.
2. New or changed UI path.
3. Changed state handling: loading, empty, error, permission, feature flag,
   cached data, reload, or local storage.
4. Visual/layout change with a concrete visual claim.
5. Smoke load only when the diff is broad/refactor-only and no narrower behavior
   changed.

One precise workflow beats five shallow page loads.

## Coverage Rules

- Prefer workflows over pages. "Create insight, add breakdown, save, reload" is
  better than "load insights page".
- Add boundary cases only when the diff adds or changes branching.
- For shared components, pick one primary usage and one contrasting usage when
  the component appears in different layouts or states.
- For visual changes, define the expected visual outcome before opening the
  browser.
- For refactors, smoke the most important visible flow and watch console/network
  errors.
- For bug fixes, recreate the reported failure before checking the fixed state
  when possible.
- Record skipped cases explicitly: mobile, permissions, feature flag off, empty
  state, dynamic IDs, or setup that local dev cannot provide.

## Examples

### Form Save

Diff signal: form fields, kea form logic, validation, submit button, toast, save
endpoint caller.

```json
{
  "kind": "browser",
  "changed_behavior": "Survey customization changes should save and persist",
  "risk": "Users think settings saved, but reload restores stale values",
  "setup": "Create or open a survey with customization enabled",
  "route": "/surveys/:id",
  "action": "Change button label, save, reload the survey editor",
  "expected": "Updated label remains visible and no error toast appears",
  "evidence": "Before save, after reload screenshot, console/network check"
}
```

### Duplicate Or Clone

Diff signal: duplicate action, copied model fields, new name generation, redirect
after clone.

```json
{
  "kind": "browser",
  "changed_behavior": "Duplicating a dashboard should create a distinct copy with copied tiles",
  "risk": "Duplicate opens the original or loses child items",
  "setup": "Use a dashboard with at least one insight",
  "route": "/dashboard/:id",
  "action": "Open more menu, duplicate, inspect the destination dashboard",
  "expected": "New dashboard title indicates a copy and tiles are present",
  "evidence": "Destination dashboard screenshot and URL"
}
```

### Empty State

Diff signal: conditional render for no results, first-run experience, blank state
copy or action.

```json
{
  "kind": "browser",
  "changed_behavior": "Empty recordings list should show the setup call-to-action",
  "risk": "New users see a blank table and cannot recover",
  "setup": "Use a project with no recordings or filter to zero results",
  "route": "/replay",
  "action": "Load replay list with no matching recordings",
  "expected": "Empty state explains why no recordings appear and shows next action",
  "evidence": "Empty state screenshot"
}
```

### Loading And Error State

Diff signal: loaders, async selectors, error banners, query retry behavior.

```json
{
  "kind": "browser",
  "changed_behavior": "Experiment results should show a recoverable error when loading fails",
  "risk": "Failures look like endless loading or a blank page",
  "setup": "Open an experiment detail page and simulate or observe failed result loading",
  "route": "/experiments/:id",
  "action": "Load results and watch the result panel",
  "expected": "Error state is visible, page shell remains usable, no uncaught console error",
  "evidence": "Error state screenshot plus console excerpt"
}
```

### Permission Boundary

Diff signal: guards, disabled buttons, role checks, organization/project access.

```json
{
  "kind": "browser",
  "changed_behavior": "Read-only users should see disabled billing actions",
  "risk": "A user sees an action they cannot perform or gets a late 403",
  "setup": "Use a user/project state without permission if available locally",
  "route": "/organization/billing",
  "action": "Open billing settings and inspect primary action controls",
  "expected": "Restricted controls are hidden or disabled with clear UI feedback",
  "evidence": "Settings screenshot or coverage gap if local role setup is unavailable"
}
```

### Feature Flag On And Off

Diff signal: `featureFlag`, `featureFlags`, persisted feature flags, gated tab or
component.

```json
{
  "kind": "browser",
  "changed_behavior": "Labs tag appears only when the feature flag is enabled",
  "risk": "Flagged UI leaks to everyone or stays hidden for enabled users",
  "setup": "Override the flag in browser state for the seed user",
  "route": "/data-management",
  "action": "Load with flag on, then clear override and reload",
  "expected": "Tagged item appears with flag on and disappears or downgrades with flag off",
  "evidence": "Two screenshots with flag state noted"
}
```

### Shared Component

Diff signal: component under `frontend/src/lib/` or shared product folder.

```json
{
  "kind": "browser",
  "changed_behavior": "LemonTable row actions should remain reachable in dense and empty states",
  "risk": "Shared table change breaks action menus across products",
  "setup": "Find one table with populated rows and one table with an empty state",
  "route": "/insights and /data-management",
  "action": "Open row action menu in populated table, then load empty table state",
  "expected": "Actions are reachable and empty state layout is not distorted",
  "evidence": "One populated screenshot, one empty state screenshot"
}
```

### Kea Logic Or State Selector

Diff signal: `logic.ts`, selectors, listeners, `kea-forms`, local storage, URL
sync.

```json
{
  "kind": "browser",
  "changed_behavior": "Insight editor should keep selected breakdown when switching display type",
  "risk": "State selector clears user input during a normal edit",
  "setup": "Create or open a trend insight with a breakdown",
  "route": "/insights/new",
  "action": "Add breakdown, switch display type, save or preview",
  "expected": "Breakdown remains selected and preview updates without console errors",
  "evidence": "Editor screenshot after switch plus console/network check"
}
```

### URL Or Routing Change

Diff signal: `urls.ts`, `sceneLogic`, route params, tabs, redirects, breadcrumbs.

```json
{
  "kind": "browser",
  "changed_behavior": "Error tracking issue tab URL should deep-link to the selected tab",
  "risk": "Reviewer can navigate by click but shared links open the wrong tab",
  "setup": "Use an existing error tracking issue if available",
  "route": "/error_tracking/:id",
  "action": "Switch tab, copy URL, reload",
  "expected": "Reload opens the same tab and breadcrumb/title still match",
  "evidence": "URL plus tab screenshot after reload"
}
```

### Search, Filter, Or Sort

Diff signal: query params, filter bars, search inputs, list sorting, pagination.

```json
{
  "kind": "browser",
  "changed_behavior": "Searching persons should update the table and persist in the URL",
  "risk": "Search appears to work but cannot be shared or reloads to unfiltered data",
  "setup": "Use existing persons or seeded events",
  "route": "/persons",
  "action": "Search for a visible person, reload the page",
  "expected": "Filtered table remains and search term is preserved",
  "evidence": "Screenshot before and after reload"
}
```

### Visual Alignment

Diff signal: class names, layout containers, spacing, icon placement, responsive
styles.

```json
{
  "kind": "visual",
  "changed_behavior": "Feedback button position selector should remain aligned in fullscreen customization",
  "risk": "Control becomes hard to read or overlaps adjacent settings",
  "setup": "Open survey customization with fullscreen presentation",
  "route": "/surveys/:id",
  "action": "Switch to customization tab and reveal position selector",
  "expected": "Selector stays aligned, text is visible, and controls do not overlap",
  "evidence": "Focused screenshot of the selector area"
}
```

### Theme Variant

Diff signal: colors, borders, backgrounds, charts, status tags, code touching
theme variables.

```json
{
  "kind": "visual",
  "changed_behavior": "Status tag contrast should work in dark and light themes",
  "risk": "Text becomes unreadable in one theme",
  "setup": "Use a route that renders the changed tag",
  "route": "/experiments",
  "action": "Capture light theme, switch to dark theme, capture again",
  "expected": "Tag text and border remain readable in both themes",
  "evidence": "Light and dark screenshots"
}
```

### Responsive Or Narrow Viewport

Diff signal: mobile classes, flex/grid changes, sidebar/header changes, text
wrapping.

```json
{
  "kind": "visual",
  "changed_behavior": "Insight header actions should wrap without overlapping on narrow width",
  "risk": "Primary action becomes hidden or text overlaps the title",
  "setup": "Open an insight detail page and use a narrow viewport",
  "route": "/insights/:id",
  "action": "Resize to a narrow desktop/mobile-ish width and inspect header",
  "expected": "Title and actions remain usable without overlap",
  "evidence": "Narrow viewport screenshot"
}
```

### Refactor With Intended No-Op Behavior

Diff signal: renamed components, extracted helpers, no product copy or visible
logic changes.

```json
{
  "kind": "browser",
  "changed_behavior": "Dashboard detail still loads after component extraction",
  "risk": "Refactor changed imports or state wiring and page crashes",
  "setup": "Use any dashboard with at least one insight",
  "route": "/dashboard/:id",
  "action": "Load dashboard, open one tile action, watch console",
  "expected": "Dashboard renders and interaction works with no new console errors",
  "evidence": "Loaded dashboard screenshot plus console check"
}
```

### Text Or Copy Change

Diff signal: user-facing string, tooltip copy, empty state wording, label.

```json
{
  "kind": "browser",
  "changed_behavior": "The invite modal should explain domain restrictions",
  "risk": "Admins misunderstand why an invite cannot be sent",
  "setup": "Open organization invite modal",
  "route": "/organization/members",
  "action": "Enter an email outside the allowed domain",
  "expected": "Validation text matches the new copy and remains visible near the field",
  "evidence": "Modal screenshot with validation text"
}
```

### Coverage Gap

Use a coverage gap when the changed behavior is real but the local stack cannot
exercise it honestly.

```json
{
  "kind": "coverage_gap",
  "changed_behavior": "Enterprise SSO setup flow changed",
  "risk": "SSO-only state is unavailable in local seed data",
  "setup": "Checked route, callers, and local feature prerequisites",
  "route": "/organization/authentication",
  "action": "Not run locally",
  "expected": "Needs an enterprise SSO-configured organization",
  "evidence": "Run note explaining the missing local prerequisite"
}
```

Coverage gaps are useful when they are specific. Avoid vague gaps like "could
not test this PR".
