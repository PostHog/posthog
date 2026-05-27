# Evidence And Output

Use this reference after the frontend QA loop completes and findings are settled.

## Evidence Upload

PR mode only. Upload is optional and must be explicitly approved before any file
leaves the developer's machine. Local mode never uploads evidence.

Required environment variable:

```bash
CLOUDINARY_URL=cloudinary://<api_key>:<api_secret>@<cloud_name>
```

The upload script loads the repo `.env` through `python-dotenv`, so no manual
sourcing is needed when invoking it through `uv run`.

If `CLOUDINARY_URL` is missing, tell the user that evidence cannot be uploaded
and the PR comment will omit local evidence links. Continue the QA run and
render a text-only evidence note instead of exposing local filesystem paths.

Before upload, show the user the exact upload set and ask for approval. Pick only
human-facing evidence:

- `frontend-qa.gif` or `frontend-qa-small.gif`, if generated
- 1-3 key screenshots that match the findings or PASS narrative

Do not upload `.md` snapshots, `console.log`, every numbered screenshot, or
uncompressed video.

Invoke with the active skill directory:

```bash
uv run python "<skill_dir>/scripts/upload-evidence.py" \
  --pr "$PR_NUMBER" \
  --run-dir ".qa-frontend/runs/<run-id>" \
  --output ".qa-frontend/runs/<run-id>/upload-manifest.json" \
  --file ".qa-frontend/runs/<run-id>/frontend-qa.gif:flow-overview" \
  --file ".qa-frontend/runs/<run-id>/<screenshot>.png:<kebab-finding-description>"
```

If the upload script is unreachable at the expected path, do not write a custom
uploader. Surface the issue and omit evidence links from the PR comment.

The script emits a manifest JSON with `uploaded`, `failed`, and
`skipped_no_env` fields. Exit codes:

- `0` - at least one file uploaded, none failed
- `1` - partial failure, some files uploaded
- `2` - `CLOUDINARY_URL` missing, nothing attempted
- `3` - fatal error

Substitute uploaded URLs into the PR comment using the `url` field from each
`uploaded` entry. Do not reconstruct URLs from `public_id`.

For failed or skipped files, omit local paths from PR comments and note
`evidence captured locally; upload failed or was skipped`. Never block the run
on upload failure. Local reports may still reference local relative paths.

Never echo `CLOUDINARY_URL`, the API secret, or raw upload response bodies into
evidence files or PR comments.

## Required Artifacts

Every run writes two artifacts before rendering anything user-facing:

1. `.qa-frontend/runs/<run-id>/findings.json` - structured findings array. The PR
   comment and local report are renders of this file.
2. A single first line on stdout: `QA-VERDICT: <verdict>` so an outer
   orchestrator can grep status without parsing markdown.

Examples:

- `QA-VERDICT: PASS`
- `QA-VERDICT: FAIL findings=3 fixes=1 coverage_gaps=2`
- `QA-VERDICT: NEEDS_INTENT ambiguities=1`
- `QA-VERDICT: FORK_READONLY findings=1`
- `QA-VERDICT: COMMENT_ONLY findings=2`

`findings.json` schema:

```json
{
  "id": "<sha1(target+step)[:12]>",
  "kind": "finding|coverage_gap|needs_intent",
  "severity": "high|medium|low",
  "confidence": "high|medium",
  "target": "/route",
  "step": "user-visible step",
  "expected": "expected outcome",
  "actual": "actual outcome",
  "evidence": ["<uploaded url or local path>"],
  "status": "new|fix-applied|suggested-patch|skipped|needs-intent",
  "fix_commit": "<sha or null>",
  "question": "intent question for needs_intent entries"
}
```

`coverage_gap` entries record routes or files the QA loop could not exercise.
They must appear as visible rows in the PR comment's test-plan table, not as a
footer note.

`needs_intent` entries record observed behavior whose expected outcome could not
be established. Local mode should ask the user before finalizing when possible.
PR mode should render these visibly instead of calling the run a clean PASS.

## Rendering

Re-read `<skill_dir>/references/pr-comment-template.md` immediately before
composing the comment or local report. Do not improvise from memory.

Before posting or printing, sanity-check the rendered report:

- First line is `## PostHog QA Frontend Report`.
- Second line is a verdict line matching one of the templates.
- Last line is `<sub>PostHog QA Frontend Report</sub>`.

If any of these are missing, read the template again and re-render.

PR mode posts one PR comment for every completed run after explicit approval:

- Clean run: PASS verdict plus coverage table.
- Confident fixes: pushed fix summary plus findings and evidence.
- Low-confidence or fork PR: findings with repro steps and suggested patches.
- Unclear expected behavior: NEEDS-INTENT verdict plus visible intent rows.
- Frontend target gaps: explicit coverage-gap rows.

Before any push, verify the comment path works. Prefer a read-only `gh api`
reachability check or a tiny stub comment workflow that is immediately cleaned
up. If comment connectivity fails, skip the push, write the final comment
markdown to stdout, and stop.

Local mode writes the rendered report to stdout and to
`.qa-frontend/runs/<run-id>/report.md`. Use the same template, but:

- Omit upload steps.
- Reference evidence by local relative path only.
- Do not call `gh api`, `gh pr comment`, or any push.

## Push Approval Gate

PR mode only, same-repo PR only, at least one confident fix commit only:

1. If `AUTO_PUSH_FIXES` was set in `$ARGUMENTS`, proceed straight to the push
   step.
2. Otherwise, after the fix loop completes and re-verification passes, stop and
   ask the user in chat: "Apply fix commit(s) <sha-list> to the PR branch?
   (y/n)". Wait for explicit "yes" / "y" / "push" / similar confirmation.
   "no" / "n" / silence means do not push. Emit the comment draft with the
   local commit SHAs and a note that the user can push manually.
3. Re-fetch and verify the remote did not move.

```bash
git fetch origin "$headRefName"
git push --force-with-lease origin HEAD:"$headRefName"
```

If the remote moved, do not push. Post or print a report explaining that local
fix commits exist but were not pushed because the PR branch changed.
