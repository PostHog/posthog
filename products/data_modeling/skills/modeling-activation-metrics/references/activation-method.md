# Finding and validating an activation definition

Activation is discovered empirically, not declared. The model you build is only as good as the definition
behind it, so run this method first.

## 1. Candidate actions

From `read-data-schema`, list early actions a new user could take in their first session/week: core feature
uses, setup steps, collaboration actions. Include count-based candidates ("did X ≥ 3 times"), not just
"did X once".

## 2. Retention lift

For each candidate, split new users into _did it early_ vs _didn't_, and compare their retention N weeks
later (use `modeling-product-usage-metrics`). Lift = retention(did) − retention(didn't). A good activation
candidate has **large, stable lift**.

Beware confounds: an action can correlate with retention without being causal (e.g. "visited settings" might
just mark already-engaged users). Prefer actions that plausibly _deliver_ the product's value.

## 3. Reach × predictive power

Score each candidate (or combination) on two axes:

- **Reach** — share of new users who hit it within the window. Too low and the metric describes a tiny elite.
- **Predictive power** — the retention lift above.

Pick the definition that keeps reach acceptable (rule of thumb: a large minority to a majority of _good-fit_
signups can hit it) while maximizing lift. Combinations ("created a dashboard AND invited a teammate") and
thresholds ("≥3 queries") usually beat any single one-time action.

## 4. Definition shape

The output of this method is a concrete, testable definition:

> A user is **activated** if, within **N days** of their first event, they **[criteria]**.

Examples: "within 7 days, ran ≥3 queries"; "within 14 days, created a project and invited ≥1 teammate".
For B2B, apply the same at the account grain: the account activates when any user meets the criteria.

Record N and the criteria explicitly — they are the model's parameters, and they'll be revisited as the
product changes. If a governed activation metric already exists in the semantic layer (see foundations
`governance.md`), reuse it instead of inventing a new one.
