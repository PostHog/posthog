# AI observability taggers

Taggers automatically add custom tags to AI generations.
The Tags pages and tagger API require the `llm-analytics-tags` feature flag.
The pages load tagger data only after the feature flag resolves as enabled.

## Creating taggers

Opening the Tags page only loads existing taggers.
An empty project stays empty until someone with editor access selects **Create tagger** and saves a tagger.
There is no automatic or bulk creation of default taggers.

Removing default creation does not change taggers that already exist.

## Planned retirement

We plan to remove Taggers as soon as Evaluations support categorical output types.
