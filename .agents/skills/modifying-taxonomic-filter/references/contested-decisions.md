# Contested decisions

These questions come up again and again. Each entry records the position
the picker currently takes, the evidence for and against it, and how to
test it if you want to reverse it. Bring evidence, not seniority.

## Should the picker reopen on the last category used?

- **Current position:** no. The picker reopens on Suggested.
- **For changing:** about 44% of users who switch away from Suggested later
  pick the same tab again (about 11% of all picker users).
- **Against changing:** a remembered tab is a hidden mode. The biggest
  measured failure is a category active while searching for something in
  another group. Recents already put the last pick at the top.
- **To test:** run it behind a flag. Primary metric: opens ending in a
  selection. Guardrails: empty-result rate, category-then-empty rate.

## Is the picker "the email or URL box"?

- **Current position:** email and URL get promoted to row 0.
- **Evidence:** they are the two biggest properties (~38% of chosen
  values). Custom properties are bigger as a group (~42%). Just under half
  of users never filter on email or URL in two weeks.
- **Implication:** promoting them is right. Designing only for them is not.

## Should categories be visible by default?

- **Current position:** hidden behind a category pill, with an optional
  docked rail.
- **Evidence:** ~93% of opens never select a category. About 2% of closes
  are docked, with the same pick rate as undocked. An earlier experiment
  saw better retention for new users with hidden categories. The effect
  faded when existing users were included.
- **Implication:** keep hidden by default and keep the rail for those who
  want it.

## Should power-user features stay?

- **Current position:** keep niche features that are cheap.
- **Evidence:** thin. Docking and include-stale have small, stable use.
  No data isolates power users.
- **Implication:** removing a cheap feature saves little. Removing an
  expensive one with almost no use (a model call per search) saves a lot.

## Should there be a natural-language or chat input?

- **Current position:** no chat input in the picker.
- **Evidence:** chat isn't discoverable: you have to know what to ask.
  Research shows natural-language interfaces are faster but less accurate,
  and users trust them too much. Some users already rescue themselves by
  asking PostHog AI.
- **To test:** let search accept a sentence and show the interpreted
  filter, editable. Measure pick rate and the share of interpreted filters
  the user edits or undoes.

## Should users be able to pin anything?

- **Current position:** yes, via the pin toggle.
- **Evidence:** pins drive ~4% of selections. Pin use doesn't change
  struggle rates.
- **Implication:** keep pins cheap. Don't give them their own tab.
