# Hedgebox demo data — reference for eval authors

Every eval in this tree (and in `ee/hogai/eval/ci`) runs against a **single, deterministic, seeded Hedgebox dataset**. Hedgebox is a fictional cloud-storage SaaS (think Dropbox). When you write an eval case, the events, properties, groups, flags, insights, and experiments below are the ground truth the agent has to work with — your `expected` queries and scorers must match this taxonomy exactly (e.g. the event is `signed_up`, not `sign_up` or `user_signed_up`).

Source of truth (read these if anything below looks stale):

- Simulation logic: `posthog/demo/products/hedgebox/models.py` (per-person session state machine + events)
- Project setup (actions/cohorts/dashboards/insights/flags/experiments): `posthog/demo/products/hedgebox/matrix.py` → `HedgeboxMatrix.set_project_up`
- Taxonomy constants (event/flag/group names): `posthog/demo/products/hedgebox/taxonomy.py`
- How evals seed it: `ee/hogai/eval/data_setup.py`

## How the data is seeded for evals

`ee/hogai/eval/data_setup.py` builds the matrix with fixed parameters — **do not assume the library defaults** (180 days / `DEMO_MATRIX_N_CLUSTERS`):

```python
HedgeboxMatrix(
    seed="b1ef3c66-5f43-488a-98be-6b46d92fbcef",  # EVAL_SEED — identical data every run
    days_past=120,        # events span ~120 days before "now"
    days_future=30,       # plus 30 days of future-dated billing events
    n_clusters=500,       # 500 clusters → ~20% companies, ~80% social circles
    group_type_index_offset=0,
)
```

- The seed is fixed, so the dataset is **byte-for-byte reproducible** — assertions on relative shapes (e.g. "signups trend over -8w") are stable, but **do not hard-code absolute counts**; they can drift if the simulation code changes.
- **Sandboxed evals** (`SandboxedDemoData` in `conftest.py`): a master Hedgebox team is generated once via `ensure_master_demo_team`, then each eval case gets its own org/team via `copy_demo_data_to_new_team` (ClickHouse `INSERT ... SELECT` copy + `set_project_up` re-run + taxonomy re-inference). Each case is isolated; the seeded user is **"Karen Smith"**.
- **CI evals** reuse one org/team via `create_demo_org_team_user`.
- Events span both past (`days_past`) and future (`days_future` — `paid_bill` events are scheduled forward). When choosing date ranges in expected queries, prefer relative ranges like `-30d`, `-8w`, `-6m`.
- Most insights/dashboards are built with `filterTestAccounts=True`. The team has `test_account_filters` configured, and a "Signed-up users" cohort exists.

## Event taxonomy (custom events)

These are the custom events the simulation captures. Property keys are exact.

| Event                  | Properties                                                                                           | Notes                                                                                           |
| ---------------------- | ---------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `signed_up`            | `from_invite` (bool)                                                                                 | `False` for new account, `True` when joining a team via invite                                  |
| `logged_in`            | —                                                                                                    |                                                                                                 |
| `logged_out`           | —                                                                                                    |                                                                                                 |
| `uploaded_file`        | `file_type` (mime str), `file_size_b` (int bytes), `used_mb` (int), optional `file_name` (hex, ~50%) |                                                                                                 |
| `downloaded_file`      | `file_type`, `file_size_b`, `file_name` (hex)                                                        | also fired (~70%) when viewing a shared file                                                    |
| `deleted_file`         | `file_type`, `file_size_b`                                                                           | no `file_name`                                                                                  |
| `shared_file_link`     | `file_type`, `file_size_b`                                                                           |                                                                                                 |
| `upgraded_plan`        | `previous_plan`, `new_plan` (plan strings, see below)                                                |                                                                                                 |
| `downgraded_plan`      | `previous_plan`, `new_plan`                                                                          |                                                                                                 |
| `invited_team_member`  | —                                                                                                    | business plans only                                                                             |
| `removed_team_member`  | —                                                                                                    | business plans only                                                                             |
| `paid_bill`            | `amount_usd` (float), `plan` (plan string)                                                           | **server-side** event (`$lib = posthog-python`), future-dated every 30 days after first upgrade |
| `$feature_flag_called` | `$feature_flag`, `$feature_flag_response`, `<flag_key>`                                              | fired at session start, only for experiment flags                                               |

Standard autocapture/web events are also present: `$pageview`, `$pageleave`, `$autocapture` (only for two outbound ad clicks, with `$event_type=click` and `$external_click_url`), `$identify`, `$groupidentify`. Error-tracking demo `$exception` events also exist (see "Error tracking" below).

`file_size_b` is in **bytes** (up to ~7 GB); `used_mb` despite its name holds the byte sum of an account's files. Don't assume the unit from the name.

### Key URLs (for `$pageview` / path analysis)

Site is `https://hedgebox.net`. Common pages: `/` (home), `/pricing/`, `/signup/`, `/login/`, `/files/`, `/files/{id}/`, `/account/settings/`, `/account/billing/`, `/account/team/`, `/mariustechtips/` (sponsored YouTube landing page), `/invite/{id}/`.

## Person & group taxonomy

- **Person properties**: `email`, `name` (set on `$identify` after signup), plus standard GeoIP/initial props (`$geoip_country_code`, `$geoip_city_name`, `$geoip_subdivision_1_code`, `$initial_referring_domain`, `$browser`, `$os`, `$device_type`, etc.). ~71% of users are in the US (heavily California / San Francisco). Internet Explorer users have lower affinity (worse conversion) by design.
- **Groups**: one group type, `account` (group_type_index 0). Set via `$groupidentify` with `$group_set` properties: `name`, `industry` (null for personal accounts), `used_mb`, `file_count`, `plan`, `team_size`. Use `account` as the group when an eval needs group math (e.g. `paid_bill` unique-group counts).

### Plans (`HedgeboxPlan`)

Plan strings used in `plan` / `previous_plan` / `new_plan`: `personal/free`, `personal/pro`, `business/standard`, `business/enterprise`. Personal clusters start on `personal/free`, company clusters on `business/standard`. Monthly bill: free $0, pro $10, business/standard $10×seats, business/enterprise $20×seats. Upgrade path is free→pro and standard→enterprise.

## Feature flags & experiments

One **plain flag**: `file-previews` (boolean, restricted to an internal email allowlist — no exposure events fired for it).

**Experiment flags** all emit `$feature_flag_called` exposures and are only active during a fraction of the 120-day window. Use these exact keys when an eval touches experiments:

| Flag key                         | Variants                      | Status in seeded data                                                                                 |
| -------------------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------- |
| `onboarding-test-v1`             | control / red / blue          | completed, **won** (red), legacy format                                                               |
| `file-engagement-v2`             | control / red / blue          | **running** (last ~30% of window)                                                                     |
| `pricing-page-v3`                | control / test                | completed, **inconclusive**                                                                           |
| `sharing-incentive-v1`           | control / test                | completed, **lost**                                                                                   |
| `upgrade-prompt-v1`              | control / aggressive / subtle | **running** (recent)                                                                                  |
| `team-collab-v1`                 | control / test                | **stopped early**                                                                                     |
| `retention-nudge-v1`             | control / test                | **draft** (never active → no exposures)                                                               |
| `bias-warning-demo-uneven-split` | control (90%) / test (10%)    | running; ~2% of users flip variant mid-experiment (triggers the multi-variant exclusion bias warning) |

Variants actually change behavior (e.g. onboarding variant alters signup success rate; file-engagement variant multiplies upload/share rates) — so experiment results are non-trivial, not flat.

## What `set_project_up` creates (insights the agent can find/reuse)

After simulation, the team is populated with named artifacts. Agents doing retrieval/insight evals will encounter these — match names exactly:

- **Actions**: "Interacted with file" (upload/download/delete/share), "Visited Marius Tech Tips campaign".
- **Cohorts**: "Signed-up users" (+ internal test-users cohort wired into `test_account_filters`).
- **Dashboards**: "🔑 Key metrics" (primary, pinned), "💸 Revenue" (pinned), "🌐 Website".
- **Insights** include: "Weekly signups", "Last month's signups by country" (world map), "Activation" (`signed_up` → "Interacted with file" → `upgraded_plan`), "New user retention", "Active user lifecycle", "Weekly file volume", "Monthly app revenue" (`paid_bill` SUM `amount_usd`), "Bills paid", "Daily unique visitors over time", "Most popular pages", "Homepage view to signup conversion", "User paths starting at homepage".
- **Endpoints**: `weekly-signups`, `monthly-revenue`, `signups-by-country`, `daily-active-users`.
- **Property group** "File Stats": `file_size_b` (numeric, required), `file_type`, `file_name`.
- **Error tracking** issues (with `$exception` events): "Checkout API timeout" (`TimeoutError`), "File preview render failure" (`RenderError`), "Team invite rejected" (`TypeError`).
- **Data warehouse** tables (when object storage enabled): `paid_bills`, `signups`, `uploaded_files`, `plan_changes`, plus an `extended_properties` table joinable to persons on email.

## Practical tips for eval authors

- Reference events/props by their **exact** names from the tables above — a mismatch is the most common reason an otherwise-correct agent output scores wrong.
- Prefer relative date ranges (`-30d`, `-8w`, `-6m`) and shape-based assertions over absolute counts.
- Set `filterTestAccounts=True` in expected queries when mirroring the seeded insights/dashboards.
- For group/account-level math use the `account` group type (index 0).
- The whole dataset is deterministic under `EVAL_SEED`; if you change the simulation in `posthog/demo/products/hedgebox/`, expected fixtures across `ci/` and `sandboxed/` may need re-baselining.
