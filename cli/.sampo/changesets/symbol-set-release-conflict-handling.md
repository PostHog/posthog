---
cargo/posthog-cli: patch
---

Symbol set uploads now ask the server to resolve release conflicts per chunk (`skip_release_on_conflict`) when `--skip-release-on-fail` is enabled (the default), so one already-uploaded chunk no longer strips the release association from every other chunk in the batch. Against older servers the previous behavior is unchanged: the whole upload is retried without release IDs, and the warning now says how many symbol sets lose their release association. Deterministic API rejections (4xx other than 408/429) are no longer retried three times before failing.
