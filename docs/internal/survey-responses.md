# Survey response results

Survey results always include captured answers, regardless of the survey's response collection setting.
This includes answers sent before completion and answers attached to partially completed dismissal or abandonment events.
Changing the collection setting does not hide answers already captured.

Events with the same submission ID appear as one response, with the latest available answer to each question.
Events without a submission ID remain separate responses.
An unfinished submission is labeled **Dismissed** when its latest response event is a dismissal, and **Abandoned** otherwise.
**Abandoned** means no completion has been captured yet; it does not require a page-unload event or an inactivity timeout.
A submission that later completes is shown as completed.

The responses table, question charts, response counts, and summaries include these answers automatically.
Dismissals and abandonments with no answers do not count as responses.

Survey performance appears on both the Summary and Responses tabs in the redesigned survey view.
It includes a compact row with counts and percentages for **Completed**, **Dismissed**, and **Abandoned** responses.
These percentages use all responses matching the current filters as their denominator, including archived responses when selected.
Each submission counts once in this breakdown, even when the performance summary counts unique people.
The performance bar labels dismissals with no answers separately from responses.
