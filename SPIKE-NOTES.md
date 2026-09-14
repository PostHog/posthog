# Spike notes: create a flag in additional projects at creation time

Frontend-only spike.
The new-flag form gets an "Also create in these projects" multi-select; after the normal create, the client calls the org-level `copy_flags` endpoint with the chosen targets.

## What the UX feels like

- The picker sits in the main settings card under the Enabled switch, marked optional.
  It only renders during creation and only when the user can access more than one project, so the common single-project case is untouched.
- One decision at create time replaces the create-then-copy round trip through the Projects tab.
  That is the point of the feature and it holds up: the flow reads as "create here, and also there".
- Double-submission through the copy phase is blocked, but not by a button spinner: `featureFlagLoading` makes `FeatureFlag.tsx` swap the whole form for a skeleton while the save and copies run.
  A button-level loading state would need a dedicated save loader key (today `loadFeatureFlag` and `saveFeatureFlag` share one), which changes what every flag save looks like - a follow-up PR, not spike scope.
  With many targets the skeleton just sits there with no per-project progress.
- Outcomes are toasts: success lists the projects the flag landed in; approval-pending targets and hard failures come out as separate clauses of a warning toast.
  For 2-3 targets a toast is enough. For more, the `BulkCopyFlagsModal` results view (per-project list, overwrite markers, warnings) is the better shape.
- Verified in the local app (dev stack pointed at the spike commit, extra projects seeded) plus jest and code reading.
  Setup note: the master checkout's database had drifted 52 migrations behind and 500'd every page until `manage.py migrate` ran - unrelated to this change.

## Rough edges found

1. **Copy semantics, not create semantics.**
   `copy_flags` overwrites an existing flag with the same key in a target project (`update_existing_target` defaults to true).
   The spike now surfaces this: the picker's info text warns about it, and the toast reports overwrites in their own clause at warning level (`updated_existing` from the response).
   Still, an overwrite after the fact is not consent: before shipping, either pre-check colliding keys via `api.organizationFeatureFlags.get` and mark those options, or give the backend a create-only mode (see below).
2. **The copy is client-side and non-atomic.**
   The create returns, then the browser issues the copy.
   Closing the tab in between leaves the flag in one project only - the exact failure this feature exists to prevent, just with a smaller window.
   There is also no retry affordance: a failed copy leaves only a toast, and the user has to find the Projects tab and copy manually.
3. **Toast ordering.** The copy-outcome toast fires before "Feature flag saved" because the copy runs inside the save loader. Cosmetic.
4. **Target cap.** The picker caps selection at 50 (`BULK_COPY_MAX_TARGET_PROJECTS`, mirroring the backend's `max_length`), so an over-limit request can no longer be submitted.
5. **Targets are not permission-filtered.**
   The picker lists every team in the org; per-target RBAC is enforced by the backend and surfaces as a failed entry.
   Correct, but pre-filtering (or a disabled reason) would be kinder.
6. **Teams vs projects.**
   The picker filters `team.id !== currentProjectId`, the same convention `FeatureFlagProjects` and `BulkCopyFlagsModal` use.
   With environments, sibling teams of the current project would appear as targets - a pre-existing ambiguity in all three surfaces, not introduced here.
7. **Telemetry** (resolved): the flow now emits `feature flag created in additional projects` with target and outcome counts, following the sibling copy surfaces.
8. **Experiment sidebar create path** (`saveSidebarExperimentFeatureFlag`) intentionally not covered, per the brief.

## What should change before shipping for real

- **Customers expect edits to carry over.**
  The CS follow-up on the originating Slack thread asked whether a config change after creation applies to the other projects.
  It does not: each copy is an independent flag, and pushing a change means a manual re-copy that overwrites the target.
  This is the strongest signal yet that the real product answer is linked flags or environments, not one-shot copy.
- **Move the operation server-side.**
  The create endpoint should accept `additional_project_ids` (or an org-level create should exist) and return per-project results in one response.
  That removes the client-side window in (2), makes approval routing consistent, and gives one place to enforce create-only semantics.
  The PR reviewer independently suggested the same shape and approved shipping the client version first.
  The same change closes the `copy_flags` evaluation-contexts gap the review bot found: running the flag serializer per target carries `evaluation_contexts` and applies the target's `require_evaluation_contexts` rule.
- **Backend need discovered: a create-only mode on `copy_flags`** (e.g. `fail_if_exists: true`), so "also create in" can never overwrite.
  Today the frontend cannot distinguish "created" from "overwrote" until the response comes back (`updated_existing`).
- Replace the outcome toast with a results dialog (reuse the `BulkCopyFlagsModal` result section) once targets can exceed 2-3.
- Decide whether the copy should inherit `_create_in_folder` and the product-intent reporting per target project.

## Implementation notes

- State lives in `featureFlagLogic`: `alsoCreateInProjects` reducer + `alsoCreateInProjectOptions` selector; reset on `saveFeatureFlagSuccess`.
- The copy runs inside the `saveFeatureFlag` loader creation branch and never throws (the flag already exists, so a copy failure must not fail the save).
- Result handling reuses `aggregateCopyResponse` / `errorMessageFrom` from `flagSelectionLogic` (exported, no behavior change there).
- Uses the generated `featureFlagsCopyFlagsCreate` client (already imported in `featureFlagLogic`) rather than the legacy `api.organizationFeatureFlags.copy` wrapper.
- Jest coverage in `featureFlagLogic.test.ts` under "creating a flag in additional projects": copy params (asserted before the loader resolves), no-copy-without-targets, copy-request failure keeping the save successful, overwrite reporting, dependency warnings, and partial failure / approval-pending surfacing.
