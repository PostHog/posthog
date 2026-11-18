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

| Value                                                             | Computed                                                                  | Stored in                    | Recomputed when                                      |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------- | ---------------------------- | ---------------------------------------------------- |
| Answer text, cited URLs, retrieved URLs, search queries           | During the run, as each engine answers (`engines.py`, `runner.py`)        | `posthog_aeo_citation_check` | Never                                                |
| `cited`, `target_urls`, `target_best_position`, `names_brand`     | With the check, against the own brands of that moment (`engines.py`)      | The check row                | The own brands change, and at the end of every run   |
| `own_domains_key`                                                 | With the check: a hash of the own domains the row was computed against    | The check row                | With the columns above                               |
| Brand catalog rows for newly cited domains                        | After each run (`sync_brands_from_run` in `catalog.py`)                   | `posthog_aeo_brand`          | Never: the sync only inserts                         |
| Brand sentiment and its scored sentences                          | On the AEO Temporal queue, after each run and from a backlog every 10 min | The check row                | The reconcile clears them when the own brands change |
| Branded or non-branded prompt                                     | At read, a word match on the prompt text                                  | Not stored                   | Not applicable                                       |
| Competitor mentions, keyword matches, top searches, cited domains | At read, from the answer text and the JSON columns                        | Not stored                   | Not applicable                                       |

The last two rows break the rule.
They are the slow reads that remain, and [the planned read model](#planned-read-model) moves them to write time.

### The reconcile

`recompute_own_citations` in `catalog.py` rewrites the settings-derived columns of every answered check whose `own_domains_key` is not the current one.
It runs about a minute after a person adds, relabels or ignores an own brand, and again at the end of every citation run.
A check that carries the current key is correct for the current own brands, so a read never has to ask.

## Reads and the indexes that serve them

| Read                                                                   | Served by                    | Columns it may use                                                                                                                           |
| ---------------------------------------------------------------------- | ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Counts over a window: checks, citations, mentions, failures, positions | `aeo_check_window_cover_idx` | `team_id`, `created_at`, `id`, `mode`, `engine`, `prompt_id`, `prompt_topic`, `check_failed`, `cited`, `names_brand`, `target_best_position` |
| The latest check of each prompt and engine                             | `aeo_check_latest_idx`       | `team_id`, `prompt_id`, `engine`, `created_at`, `id`                                                                                         |

A count that stays inside its index's columns never reads the wide rows.
A count that names one more column reads every row in the window in full, and loses the whole benefit.

- `mention_filter` in `brand.py` reads `cited` and `names_brand` only.
  `test_set_level_reads_never_load_the_answer_text` fails when the overview or the prompt list starts to read `answer_text`.
- Do not add `prompt_text`, `answer_text` or a JSON column to an index.
  Postgres refuses an index row above about 2.7 KB, a prompt can be 2,000 characters, and a refused index row fails the insert of the check.
- Check a new set-level query with `EXPLAIN (ANALYZE, BUFFERS)` on data of production shape.
  The plan must show an index-only scan with few buffers.
  A warm local database hides a wide read, because every page is already in memory.

## Adding a metric

1. Decide which kind of value it is: a fact about the answer, a value derived from settings, or a classification.
2. Store a fact when the check is written. Add it to the reconcile as well when it depends on settings.
3. Backfill the existing checks in the background, and keep the old read until the backfill is complete.
4. Read the stored value, from an index that holds every column the read needs.
5. Work that asks a model runs on the Temporal queue, apart from the reconcile, so a settings change never waits for a model.

## Planned read model

Not built yet. This section records the direction, so the remaining slow reads move the same way.

Three narrow tables hold facts about each answer, written once and joined to the brand catalog at read time.
Each row repeats the columns that reads filter on (`team_id`, `created_at`, `engine`, `mode`, `prompt_id`, `prompt_topic`), so a read needs no join back to the wide check row.

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
