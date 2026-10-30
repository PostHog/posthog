# Contested decisions

These questions come up again and again.
Each entry records the position the picker currently takes, the evidence for and against it, and how to test it if you want to reverse it.
Bring evidence, not seniority.

## Should the picker reopen on the last category used?

- **Current position:** no.
  For an ordinary selection, the picker reopens on Suggested.
  Exception: it reopens a group in `OPEN_AS_SELF_ON_REOPEN` (`types.ts`) on itself.
- **For changing:** about 24% of users who click a category tab click the same tab again on a later day (about 9% of picker users), over 90 days to 2026-10-15.
  Source: [Query 15](refreshing-product-reality.md#15-users-who-return-to-the-same-tab).
  An earlier draft said 44% and 11% with no recorded query, and no definition tried since reproduces them.
- **Against changing:** a remembered tab is a hidden mode.
  The biggest measured failure is a category active while searching for something in another group.
  Recents already put the last pick at the top.
- **To test:** run it behind a flag.
  Primary metric: engaged opens ending in a selection.
  Guardrails: empty-result rate, category-then-empty rate.

## Is the picker "the email or URL box"?

- **Current position:** email and URL get promoted to row 0.
- **Evidence:** they are the two biggest properties (~38% of chosen values).
  Custom properties are bigger as a group (~42%).
  Just under half of users never filter on email or URL in two weeks.
- **Implication:** promoting them is right.
  Designing only for them is not.

## Should categories be visible by default?

- **Current position:** hidden behind a category pill, with an optional docked rail.
- **Evidence:** ~96% of engaged opens never select a real category.
  About 1% of closes have the docked preference on, with a slightly lower pick rate (~79% vs ~86%).
  The preference persists, so this includes single-group pickers where no rail shows.
  An earlier experiment saw better retention for new users with hidden categories.
  The effect faded when existing users were included.
- **Implication:** keep hidden by default and keep the rail for those who want it.

## Should power-user features stay?

- **Current position:** keep niche features that are cheap.
- **Evidence:** thin.
  Docking and include-stale have small, stable use.
  No data isolates power users.
- **Implication:** removing a cheap feature saves little.
  Removing an expensive one with almost no use saves a lot.

## Should there be a natural-language or chat input?

- **Current position:** no chat input in the picker.
- **Evidence:** chat isn't discoverable: you have to know what to ask.
  Research shows natural-language interfaces are faster but less accurate, and users trust them too much.
  Some users already rescue themselves by asking PostHog AI.
- **To test:** let search accept a sentence and show the interpreted filter, editable.
  Measure pick rate and the share of interpreted filters the user edits or undoes.

## Should users be able to pin anything?

- **Current position:** yes, via the pin toggle.
- **Evidence:** pins drive ~4% of selections.
  Pin use doesn't change struggle rates.
- **Implication:** keep pins cheap.
  Don't give them their own tab.
