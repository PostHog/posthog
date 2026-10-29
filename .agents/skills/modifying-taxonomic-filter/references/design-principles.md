# Design principles

Principles for picker changes, each grounded in the picker's own data and in published search and UX research.
Use them to argue for or against a change.
If your change breaks one, say so in the PR and bring evidence.

## 1. Recognition beats recall

Users pick far more often from what they can see (Suggested, recents, the top rows) than from what they have to remember.
Recents users struggle much less.
Nielsen's heuristic of recognition over recall says the same.

**So:** show likely items before the user types.
Don't make people know which group a thing lives in.

## 2. No hidden modes

A selected category silently narrows search, and that is the biggest measured failure.
Research on mode errors finds the same: users forget a mode they can't see while they are focused on the task.

**So:** if state changes what search returns, make it visible at the point of typing, or don't let it narrow search at all.

## 3. Never a dead end

Most empty results are the right word in the wrong scope.
Baymard's e-commerce search research finds "no results" pages are a top cause of abandonment, and suggestions on them recover a large share.

**So:** an empty state shows where the term exists, close matches, or a way to add it.
A bare "no results" is a bug.

## 4. The top of the list is the product

About half of picks are row 0 and most are in the top three.
Searchers mostly look at the first few results.

**So:** ranking changes are high-stakes.
A good item at row 6 is nearly invisible.
Demoting a popular item is a regression.

## 5. Users search with their words, not ours

Users type `email`, `user`, `url`, and type-names like `person`.
The vocabulary problem (Furnas et al.) shows two people pick the same word for a thing well under a fifth of the time.

**So:** map common words and synonyms to the right items.
Treat a group name typed as a query as a request to see that group.

## 6. Fast, but honest about failure

p50 latency is fine.
Slow tails and silent failures hurt more than the median.
Users tolerate a short wait when they can see progress, and give up when a failure looks like loading or like "no results".

**So:** show the first usable results without waiting for optional requests, and show an error with a retry when a request fails.

## 7. Engineers trust what they can check

Many users are engineers who read the filter they built.
Research on natural-language and AI interfaces finds people over-trust confident output and miss errors.

**So:** any AI or natural-language help should produce a normal, editable filter the user can see before it applies.
Don't hide the interpretation.

## 8. Defaults serve most users; options serve the rest

Most users never open a category.
A minority dock the rail or use include-stale.

**So:** design defaults for the majority.
Keep cheap options for the minority, and don't let them complicate the default path.
