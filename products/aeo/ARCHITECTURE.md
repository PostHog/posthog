# AI visibility architecture

How the AI visibility data is written and read, and the rule that decides where new work goes.
[README.md](README.md) covers setup, the API and the engines.

## The rule

**Store a value when the answer is written. Count stored values when the page is read.**

An answer holds up to 8,000 characters and a check row is wide, so a read that scans answer text or unpacks JSON for every check in a window gets slower with every run.
A page that people open rarely finds few of those rows in the database cache, so a wide read pays for cold disk reads as well.

Two kinds of stored value follow different rules:

- **A fact about the answer** depends only on the answer: its text, the URLs it cites, the searches the engine ran.
  It is written once and never recomputed.
- **A value derived from the project's settings** depends on the answer and on the brand catalog: whether the answer cites or names an own brand.
  It is recomputed when the settings change, by a background task, never by a read.

A classification that only labels a stored fact, such as own, competitor or ignored, is a join against the brand catalog at read time.
The catalog is small, so the join is cheap, and a relabel needs no recompute.

## When each value is computed

| Value                                                                           | Computed                                                                  | Stored in                                                | Recomputed when                                      |
| ------------------------------------------------------------------------------- | ------------------------------------------------------------------------- | -------------------------------------------------------- | ---------------------------------------------------- |
| Answer text, cited URLs, retrieved URLs, search queries                         | During the run, as each engine answers (`engines.py`, `runner.py`)        | `posthog_aeo_citation_check`                             | Never                                                |
| `cited`, `target_urls`, `target_best_position`, `names_brand`, `prompt_branded` | With the check, against the own brands of that moment (`engines.py`)      | The check row                                            | The own brands change, and at the end of every run   |
| One row per cited URL, one row per search the engine ran                        | With the check (`write_facts` in `facts.py`)                              | `posthog_aeo_check_citation`, `posthog_aeo_check_search` | Never                                                |
| `own_domains_key`                                                               | With the check: a hash of the own domains the row was computed against    | The check row                                            | With the columns above                               |
| Brand catalog rows for newly cited domains                                      | After each run (`sync_brands_from_run` in `catalog.py`)                   | `posthog_aeo_brand`                                      | Never: the sync only inserts                         |
| Brand sentiment and its scored sentences                                        | On the AEO Temporal queue, after each run and from a backlog every 10 min | The check row                                            | The reconcile clears them when the own brands change |
| Competitor mentions and keyword matches                                         | At read, from the answer text                                             | Not stored                                               | Not applicable                                       |

The last row breaks the rule.
Those are the slow reads that remain, and [the planned read model](#planned-read-model) moves them to write time.

### The reconcile

`recompute_own_citations` in `catalog.py` rewrites the settings-derived columns of every answered check whose `own_domains_key` is not the current one.
It runs about a minute after a person adds, relabels or ignores an own brand, and again at the end of every citation run.
A check that carries the current key is correct for the current own brands, so a read never has to ask.

## Reads and the indexes that serve them

| Read                                                                   | Served by                                                               | Columns it may use                                                                                                                                             |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Counts over a window: checks, citations, mentions, failures, positions | `aeo_check_window_cover_idx`                                            | `team_id`, `created_at`, `id`, `mode`, `engine`, `prompt_id`, `prompt_topic`, `check_failed`, `cited`, `names_brand`, `prompt_branded`, `target_best_position` |
| The latest check of each prompt and engine                             | `aeo_check_latest_idx`                                                  | `team_id`, `prompt_id`, `engine`, `created_at`, `id`                                                                                                           |
| Cited domains and pages                                                | `aeo_check_citation_window_idx`, joined to `aeo_check_window_cover_idx` | `team_id`, `created_at`, `citation_check_id`, `host`, `domain`. A read that needs `url` loads the narrow citation rows                                         |
| Searches the engines ran                                               | `aeo_check_search_window_idx`, joined to `aeo_check_window_cover_idx`   | `team_id`, `created_at`, `citation_check_id`, `query`                                                                                                          |

A count that stays inside its index's columns never reads the wide rows.
A count that names one more column reads every row in the window in full, and loses the whole benefit.

- `mention_filter` in `brand.py` reads `cited` and `names_brand` only, and `check_segment_filter` reads `prompt_branded` only.
  `test_set_level_reads_never_load_the_wide_columns` fails when the overview or the prompt list starts to read `answer_text`.
- Do not add `prompt_text`, `answer_text` or a JSON column to an index.
  Postgres refuses an index row above about 2.7 KB, a prompt can be 2,000 characters, and a refused index row fails the insert of the check.
- Check a new set-level query with `EXPLAIN (ANALYZE, BUFFERS)` on data of production shape.
  The plan must show an index-only scan with few buffers.
  A warm local database hides a wide read, because every page is already in memory.

## Stored results

The overview and the rankings are the same for every person who opens the page, and their inputs change a few times a day.
`stored_results.py` keeps their results, so a read is one cache lookup and no query on the checks.

- **A result is stored under a data version.** Every writer calls `bump_data_version_on_commit` after it changes what a read returns, and a read looks only under the current version, so it never gets a result from before a write.
- **A saved or deleted prompt, brand or engine setting bumps through signals** (`signals.py`). Checks have no receiver, because a delete receiver makes a team deletion load its whole check history. Every write to the checks is a bulk write, and the code that makes it bumps: the runner, the reconcile, the sentiment scorer and the fact backfill. So do the brand sync and the prompt import. A new bulk write needs its own bump.
- **The refresh fills old checks first.** When a check has no `prompt_branded` or no fact rows, the refresh task starts the reconcile, which fills both and starts the refresh again. A deploy that adds a stored value therefore needs no manual backfill.
- **The views the page opens on are always stored.** `refresh_stored_results` computes the default window after every reconcile, and a beat task computes it again every 10 minutes. A filtered view is computed on its first read and stored for the next.
- **The version lives on the Redis primary**, and a failed bump never fails the write that made it.
- **A stored result lives 30 minutes.** A writer that forgets to bump can leave an old result in use for that long at most, and for 10 minutes at most on the default views.
- **A result is stored per date range, under the days the range resolves to.** A relative range such as `-30d` resolves to new days each day in the project's timezone, so a new day is a new result. A request with no range and one that sends the default range read the same result.
- In a test, a bump waits for a commit that a `TestCase` never makes. Wrap the write in `captureOnCommitCallbacks(execute=True)` when the test reads again after it.

The stored result does not replace fast queries: the refresh runs them every 10 minutes for each project, and a filtered view runs them on its first read.

## Adding a metric

1. Decide which kind of value it is: a fact about the answer, a value derived from settings, or a classification.
2. Store a fact when the check is written. Add it to the reconcile as well when it depends on settings.
3. Backfill the existing checks in the background, and keep the old read until the backfill is complete.
4. Read the stored value, from an index that holds every column the read needs.
5. Work that asks a model runs on the Temporal queue, apart from the reconcile, so a settings change never waits for a model.

## Planned read model

Partly built. This section records the direction, so the remaining slow reads move the same way.

Three narrow tables hold facts about each answer, written once and joined to the brand catalog at read time.
Each row copies `team_id` and `created_at` from its check, so a read finds the rows of a window in the table's own index.
A read that narrows by engine, topic or the branded split joins them to `aeo_check_window_cover_idx`, which holds those columns.

The cited URL and search rows are built, and the overview and the rankings read them.
The reconcile after a run writes them once for checks recorded before the rows existed, and `backfill_aeo_check_facts` does the same on demand.
Until then such a check counts no citations and no searches.
Entity mentions are not built.

| Table           | One row per                       | Written                                        | Replaces                                               |
| --------------- | --------------------------------- | ---------------------------------------------- | ------------------------------------------------------ |
| Cited URLs      | Check and cited URL               | With the check                                 | Unpacking `cited_urls` and `top_cited_domains` at read |
| Search queries  | Check and normalized search query | With the check                                 | Unpacking and normalizing `search_queries` at read     |
| Entity mentions | Check and entity the answer names | On the Temporal queue, minutes after the check | Matching each brand's pattern against the answer text  |

- An entity mention stores the name and the kind of entity, whatever the catalog says about it.
  A new competitor that answers already name then appears with its history, and needs no rerun.
- A competitor whose name was never extracted needs one background pass over the stored answers for that name.
  The page shows that the pass is running.
- A change to the entity parser reprocesses every answer, so the parser has an evaluation set before it replaces the word match.
