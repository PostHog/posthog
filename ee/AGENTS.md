# Enterprise edition code

Do not add a file to `ee/`. The folder is deprecated and new code belongs in `posthog/` or `products/<product>/`.

The `.github/scripts/check-no-new-ee-files.py` check fails a pull request that adds any new file here. It compares paths, so an empty file counts too.

## A new file here needs human approval

1. Ask a human person for approval before making any change that adds new files to the `ee/` folder. Explain to them that the `ee/` folder is deprecated and should not accept new files.
2. If the human confirms to add the file, then add the file's exact path to the `EXEMPT` set in `.github/scripts/check-no-new-ee-files.py`.
3. State the reason for why the file was added here in the pull request description.

An agent must not do step 2 on its own. Report the blocked file to the person and let them decide.

## Extending existing code

Extend code in `ee/` only when the change cannot live in `posthog/` or a `products/` folder. Say why in the pull request description.

Tests and migrations for existing `ee/` code are new files too, so they follow the same approval.
