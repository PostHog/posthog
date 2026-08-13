# Shape

The fixture uses small, human-readable records so a timeline can show additions, edits, and deletions without domain noise.

- `commit_id` identifies a change.
- `files` records the paths touched by that change.
- `kind` describes whether the change adds, edits, or removes a file.
- File order is stable so snapshots do not change between runs.
- Empty file lists are valid for metadata-only commits.
