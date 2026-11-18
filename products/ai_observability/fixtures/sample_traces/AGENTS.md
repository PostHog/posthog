# Sample traces

Every file under `units/`, `media/`, `sets.json` and `checksums.json` is generated.
Each unit keeps the structure of real production AI events and carries no real content: an internal pipeline replaces every text, identifier and media payload.

- **Never add, edit or "fix" a unit, a media file or a set by hand, and never write a new unit from scratch.** A hand-written unit looks plausible and tests nothing real. `test_sample_traces.py` fails on any file whose hash does not match `checksums.json`; regenerating the hash does not make a hand edit acceptable.
- **Never paste production or customer content here, anonymized or not.** The repository is public, and edited real content is still derived. See "Public open source repo guidance" in the root `AGENTS.md`.
- New coverage comes from a new pipeline run owned by the AI observability team. If a case is missing, say so in the PR or ask the team; do not approximate it.
- Code that reads these files (the seed command, tests, stories) may change freely.
