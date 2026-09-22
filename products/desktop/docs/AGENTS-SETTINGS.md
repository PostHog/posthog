# Agent settings

Open Settings > Agents to manage scheduled agents. The page has three tabs:
Agents, Memory, and Setup. Each browser tab keeps its own selection.
A link to an agent or a signal opens that item. The `/agents` link opens the fleet.

Review agent reports in Self-driving. The Self-driving link and report total on
the Agents tab open that page. Old `/agents/findings` and
`/agents/scouts/findings` links also open Self-driving. Agents can create or
update reports directly, so a zero count of older signals does not mean that
agents produced no reports.

The fleet shows up to 18 recent runs for each agent. It uses one request for
these runs and one request for output totals. Output totals cover recent output
runs in the last three days. The API limits the totals to 120 output runs and
50 reports. The success rate describes only the runs shown in the table.

Each agent has Activity, Output, and Settings tabs. Activity and Output load a
three-day run window for that agent. Runs from other agents do not consume its
page limit. Output shows links to reports the agent created or updated, plus
older signal findings when present. Report links open the report in Self-driving
or its assigned space. Expanded Activity rows also show these links.
Each link shows the report title, a short summary, priority when available, and
whether the run created or updated the report. Report details load as their
cards approach the visible area and share the Self-driving cache.

The page identifies
incomplete history and keeps available data visible if a refresh fails. A run
that creates or updates a report counts as output. An agent with a failure streak
still needs attention when its run history is not available.

Interval agents with no previous run are due now. Cron schedules use the project
timezone. The page shows the cron schedule without an estimated next run time
because the config response does not include that timezone. A schedule change
applies immediately. A disabled agent can run manually for a test. An agent with
a queued or active run cannot start another run.

A run that exceeds its deadline shows a stuck status. Silence alone does not
cause an automatic pause. Resume starts a new grace period after an inactivity
pause. Use Never pause for inactivity to prevent another inactivity pause.

A failed draft request keeps the entered brief. Expanded signal cards and memory
notes keep their state when they scroll out of view. Search and sort changes
return lists to the top. Narrow windows hide secondary table columns so that
controls remain available. Run boxes show their labels on keyboard focus.

Query snapshots stay in a bounded memory cache. They do not persist to disk.
Sign-out clears the cache. Older plaintext snapshots are removed when the module
loads. Run summaries do not load remote Markdown images.
