# Editing locally with `hogli devbox:sync`

`hogli devbox:sync` mirrors the local checkout onto the box with [mutagen](https://mutagen.io), in one direction.
Local files are the source of truth, and nothing syncs back.
Use it in an agent loop: edit with local tools, let the mirror carry each change, and run the stack and checks on the box with `devbox:exec`.
This replaces committing and pushing on every iteration, or editing over Remote-SSH.

```bash
hogli devbox:start                  # the box must be running
hogli devbox:sync                   # create the mirror; re-running does nothing, so use --status
hogli devbox:exec -- bash -lc 'cd ~/posthog && pnpm --filter=@posthog/frontend typescript:check'
hogli devbox:sync --json            # sync state as JSON, for scripts and agents
hogli devbox:sync --flush           # push pending changes now
hogli devbox:sync --pause           # stop mirroring; --resume starts it again
hogli devbox:sync --terminate       # remove the mirror when done
```

## Behavior to know

- **Run it locally, from the checkout to mirror.** It walks up from the working directory to find `hogli.yaml` and `.git`, so run it from the repo root being edited, including a worktree. Never run it through `devbox:exec`.
- **Remote-only files stay.** The sync mode is `one-way-safe`, so the box's prewarmed `node_modules`, virtualenv, and `target/` are never deleted. Files that exist on the box but not locally when the mirror is created also stay, such as files the branch deleted, so remove them on the box when a check could pick them up. Lockfiles do sync, so after a lockfile change install dependencies on the box through `devbox:exec` before trusting its checks.
- **The first sync puts the box on the local branch.** A new box is on `master`, and the first mirror shows every tracked file that differs between the two checkouts as a conflict. So before it creates the mirror, `devbox:sync` compares the local branch and SHA with the box's checkout. When they differ and the box has no uncommitted changes, it fetches the local SHA from `origin` on the box and checks it out there. Push the branch first, because the box can't fetch local-only commits. When the box has uncommitted changes, the SHA isn't on `origin`, or the box branch has commits the local one lacks, it leaves the box alone, warns, and mirrors anyway. Pass `--checkout-branch` to fail instead, or `--no-checkout-branch` to skip the check. Local uncommitted edits still conflict on the first sync. Conflicts are per path: other files, including new ones, still sync.
- **A stopped box's mirror waits paused.** `devbox:stop` pauses the mirror, and `devbox:start` resumes it once the box is up. A plain `devbox:sync` leaves a paused mirror paused, so resume one that a box started elsewhere with `--resume`.
- **The mirror never starts a box.** Its SSH connections run with Coder's autostart off, so a mirror to a box Coder stopped fails until the box runs again.
- **Don't edit mirrored files on the box.** Remote edits fight the local source of truth. `devbox:open --vscode` and `--cursor` warn when a sync is active.
- **Check before recreating.** Compare the box's branch and SHA and the sync state first. If they match and no source file conflicts, keep the existing mirror. Source-file conflicts block reliable QA until resolved. A conflict in box-local config is acceptable when tracked source is clean.
- **`.env` and `.env.local` don't sync.** The box writes its own `.env` at startup, and a worktree copies the main checkout's `.env`, so each side keeps its own. Change the box's copy on the box.

## Ignore rules

hogli seeds `~/.hogli/mutagen.yml` from its packaged defaults, and the user can edit it.
hogli refreshes an unedited copy when it ships new defaults.
It leaves an edited copy alone, and also a copy seeded before hogli recorded the seed.
To pick up new defaults in either case, delete the file and run `hogli devbox:setup` again.
A mirror reads the file only when it is created, so after any change to the file, recreate the mirror with `hogli devbox:sync --terminate` and then `hogli devbox:sync`.
