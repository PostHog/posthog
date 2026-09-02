# Evidence And Output

Use this reference after the frontend QA loop completes and findings are settled.

## Evidence Upload

PR mode only. Upload is optional and must be explicitly approved before any file leaves the developer's machine. Local mode never uploads evidence.

Attach the evidence to the PR comment itself with `gh pr comment --attach`. The flag repeats, takes up to 50 files per command, uploads each one to GitHub, and rewrites the matching local reference in the comment body to the uploaded asset. It accepts png, jpg, gif, webp, svg, mp4, mov, and webm up to 10 MB - including the animated `frontend-qa.webp` demo reel - and needs only the developer's normal `gh` login with write access to the repo, no extra secret. It needs gh 2.99.0 or later, so check `gh --version` before planning around it. It also needs an OAuth login or a PAT: a GitHub App user token (`ghu_`), which cloud task sandboxes carry, is rejected with `unsupported authentication type`. Fall back to `hogli pr:upload-image` and `hogli pr:upload-video` in either case, pasting the markdown they print into the comment body.

Uploads are PUBLIC and PERMANENT: the attachment URL keeps serving even after the comment is edited or deleted, so an upload cannot be taken back. Before attaching, show the user the exact upload set and ask for approval. Attach only reviewed evidence that does not show secrets, private customer data, or unrelated local context. Pick only human-facing evidence:

- `frontend-qa.webp`, only if generated and inspected as readable
- 1-3 annotated key screenshots that match the findings or PASS narrative

Do not attach `.md` snapshots, `console.log`, or every numbered screenshot. If the demo pass produced an MP4, include it in the same approved upload set; GitHub renders attached video as a player, so it needs no alt text and no manual drag into the comment editor. If the reel is less clear than the annotated stills, omit it from the upload set and use the PNGs instead.

Before asking for upload approval, inspect the final evidence exactly as it will be posted. Each image must make the claimed PASS, FAIL, SKIP, or NEEDS INTENT row understandable without reconstructing the browser session. If an image only shows the page header, hero, empty shell, or setup state while the actual proof is below the fold or too small to read, do not upload it. Recapture, crop through browser positioning, or add a clearer annotated still first.

When a screenshot uses deliberately odd test data, add a one-sentence explanation in the report near the evidence or coverage row. Do this for cases where the visible data is technically valid but not self-explanatory, such as edge-case email syntax, encoded URLs, timezone boundaries, or synthetic billing states.

Write the comment body to a file with the evidence referenced by its local path, then post and upload in one command after the user approves the upload set:

```bash
gh pr comment <number> --body-file ".qa-frontend/runs/<run-id>/comment.md" \
  --attach ".qa-frontend/runs/<run-id>/frontend-qa.webp" \
  --attach ".qa-frontend/runs/<run-id>/<screenshot>.annotated.png" \
  --attach ".qa-frontend/runs/<run-id>/frontend-qa.mp4"
```

Each `![Login error state](.qa-frontend/runs/<run-id>/<screenshot>.annotated.png)` in the body becomes the uploaded asset and keeps the alt text written there, so write alt text that describes the finding. A file the body never references is appended to the end of the comment instead, which is a fallback rather than the plan. Alt text can also follow the path after `#`, as in `--attach './shot.png#Login error state'`; video renders as a player and takes no alt text.

Unlike the older hogli uploader, this needs no trusted tree: `gh` is a system binary rather than repo code, so it is safe to run from the PR checkout.

There is no `--yes` speed bump on `--attach`, and the command uploads and posts together. Never run it before the user approved this exact upload set in the conversation.

If some attachments fail, `gh` still posts the comment with the ones that succeeded and exits non-zero. Read the posted comment before reporting the run done. If the command fails outright (no token, no write access, network), do not write a custom uploader and do not expose local filesystem paths in the PR comment; note `evidence captured locally; upload failed or was skipped` and continue. Never block the run on upload failure. Local reports may still reference local relative paths.

## Required Artifacts

Every run writes two artifacts before rendering anything user-facing:

1. `.qa-frontend/runs/<run-id>/findings.json` - structured findings array. The PR comment and local report are renders of this file.
2. A single first line on stdout: `QA-VERDICT: <verdict>` so an outer orchestrator can grep status without parsing markdown.

The verdict words are exactly the template's verdict words (see `pr-comment-template.md`): `PASS`, `FIXED`, `FAIL`, `NEEDS-INTENT`, `REPORT-ONLY`. Fork and comment-only runs use `REPORT-ONLY` with a `reason=` token. Examples:

- `QA-VERDICT: PASS`
- `QA-VERDICT: FIXED findings=1 fixes=1`
- `QA-VERDICT: FAIL findings=3 fixes=0 coverage_gaps=2`
- `QA-VERDICT: NEEDS-INTENT ambiguities=1`
- `QA-VERDICT: REPORT-ONLY findings=1 reason=fork`

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

`coverage_gap` entries record routes or files the QA loop could not exercise. They must appear as visible rows in the PR comment's test-plan table, not as a footer note.

`needs_intent` entries record observed behavior whose expected outcome could not be established. Local mode should ask the user before finalizing when possible. PR mode should render these visibly instead of calling the run a clean PASS.

## Rendering

Re-read `<skill_dir>/references/pr-comment-template.md` immediately before composing the comment or local report. Do not improvise from memory.

Throughout the run, append every piece of setup you create or rely on to `.qa-frontend/runs/<run-id>/run-notes.md` (the same run directory as every other artifact) as it happens: stack choice, workspace and login, org/plan state, data created or seeded, flag/theme overrides, degraded processes. The report's required Setup section is rendered from those notes, and it is what lets a reader decide whether to trust each PASS.

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

Before any push, verify the comment path with a read-only `gh api` reachability check. Do not create temporary stub comments. If comment connectivity fails, skip the push, write the final comment markdown to stdout, and stop.

Local mode writes the rendered report to stdout and to `.qa-frontend/runs/<run-id>/report.md`. Use the same template, but:

- Omit upload steps.
- Reference evidence by local path only, as clickable markdown links relative to the report file (see the local-report links rule in `pr-comment-template.md`).
- Do not call `gh api`, `gh pr comment`, or any push.

## Push Approval Gate

PR mode only, same-repo PR only, at least one confident fix commit only:

1. If `AUTO_PUSH_FIXES` was set in `$ARGUMENTS`, proceed straight to the push step. Auto-push also implies approval for the fix-summary PR comment: never push a fix without the comment that discloses it, and if the comment cannot be posted, do not push.
2. Otherwise, after the fix loop completes and re-verification passes, stop and ask the user in chat: "Apply fix commit(s) <sha-list> to the PR branch? (y/n)". Wait for explicit "yes" / "y" / "push" / similar confirmation. "no" / "n" / silence means do not push. Emit the comment draft with the local commit SHAs and a note that the user can push manually.
3. Push with a plain, non-force push:

```bash
PR_HEAD_REF=$(gh pr view "$PR_REF" --json headRefName --jq '.headRefName')
test -n "$PR_HEAD_REF"
GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null \
  git push origin "$PR_HEAD_REF"
```

Never force-push. The push names the local PR branch, not `HEAD`, so it works from any checkout state. The fix commits sit on top of the checked-out PR head, so a non-fast-forward rejection means the remote moved during the run: do not retry and do not fetch-and-force. Post or print a report explaining that local fix commits exist but were not pushed because the PR branch changed.
