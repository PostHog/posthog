# Editing locally with `hogli devbox:sync`

`hogli devbox:sync` mirrors the local checkout onto the box with [mutagen](https://mutagen.io), in one direction.
Local files are the source of truth, and nothing syncs back.
Use it in an agent loop: edit with local tools, let the mirror carry each change, and run the stack and checks on the box with `devbox:exec`.
This replaces committing and pushing on every iteration, or editing over Remote-SSH.

```bash
hogli devbox:start                  # the box must be running
hogli devbox:sync                   # create the mirror; re-running only reports status
hogli devbox:exec -- bash -lc 'cd ~/posthog && pnpm --filter=@posthog/frontend typescript:check'
hogli devbox:sync --json            # sync state as JSON, for scripts and agents
hogli devbox:sync --flush           # push pending changes now
hogli devbox:sync --pause           # stop mirroring; --resume starts it again
hogli devbox:sync --terminate       # remove the mirror when done
```

## Behavior to know

- **Run it locally, from the checkout to mirror.** It walks up from the working directory to find `hogli.yaml` and `.git`, so run it from the repo root being edited, including a worktree. Never run it through `devbox:exec`.
- **Remote-only files stay.** The sync mode is `one-way-safe`, so the box's prewarmed `node_modules`, virtualenv, and `target/` are never deleted. Lockfiles do sync, and the box reconciles dependencies on its next start.
- **A feature branch conflicts on first sync.** A new box is on `master`, so every file the branch changed shows as a conflict in the sync state. Conflicts are per path: other files, including new ones, still sync. Resolve a path, or check out the same branch on the box, only when that file must be mirrored.
- **Don't edit mirrored files on the box.** Remote edits fight the local source of truth. `devbox:open --vscode` and `--cursor` warn when a sync is active.
- **Check before recreating.** Compare the box's branch and SHA and the sync state first. If they match and no source file conflicts, keep the existing mirror. Source-file conflicts block reliable QA until resolved. A conflict in box-local config such as `.env` is acceptable when tracked source is clean.

## Ignore rules

hogli seeds `~/.hogli/mutagen.yml` from its packaged defaults, and the user can edit it.
hogli refreshes an unedited copy when it ships new defaults.
It leaves an edited copy alone, and also a copy seeded before hogli recorded the seed.
To pick up new defaults in either case, delete the file and run `hogli devbox:setup` again.
