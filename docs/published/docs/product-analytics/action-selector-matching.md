# Action selector matching

Actions that match elements by CSS selector used to match more elements than their selector describes. We have fixed this. If one of your actions was affected, its counts are now lower, including for dates in the past.

## What changed

Conditions written together in a selector have to be met by the same element. A selector like `div.btn` means one element that is both a `div` and has the class `btn`.

Before the fix, those conditions could be met by different elements. A `div` anywhere above a `.btn` in the page would satisfy `div.btn`, so the action counted clicks it was never meant to count.

Two other combinators changed at the same time:

- `>` now means a direct child, as it does in CSS. Before, it reached past elements in between.
- A space now means any descendant. Before, a selector like `section button` only matched when the `button` sat directly under the `section`.

## Why past dates changed too

PostHog stores the elements of every autocapture event as they were when the event happened, and works out which actions match when you run a query. It does not store the match itself.

So correcting how selectors are matched changes the answer for every date, not only for events captured after the fix. An insight you looked at last month can show a lower number today.

## Which actions were affected

Most were not. For most selectors we could rewrite the selector so its counts stayed the same, and we did that for you. Those actions kept their numbers and read correctly under the new rules.

For a smaller set there was no rewrite that kept the old counts. Those actions were over-counting, and there is no version of the selector that reproduces the old number while describing what you meant. Their counts dropped.

If one of your insights uses an affected action, the insight shows a notice naming the action and the selectors involved.

## What to do

Open the action and check that its selector describes the element you want.

If the counts are now lower than you expect, the selector is probably matching fewer elements than you intended. Loosen it: use a space instead of `>` to allow elements in between, or drop a condition that the target element does not actually carry.

The [toolbar](/docs/toolbar) is the fastest way to check. Open it on your site and select the element you want the action to match, and it writes a selector that matches that element under the current rules.
