---
name: creating-in-app-product-tour
description: 'Build an in-app product tour that guides PostHog users through a feature inside the PostHog UI itself. Targeting via feature flag, visibility via custom UI built on existing LemonUI primitives, with reusable component + kea logic so every tour stays consistent. Use when the user asks to add a walkthrough, guided tour, onboarding overlay, coachmark, hint flow, or step-by-step intro for a PostHog feature. Do NOT use this skill for the customer-facing Product Tours product (toolbar-authored, posthog-js SDK rendered) — that lives in `products/product_tours/` and is a different system.'
---

# Creating an in-app product tour

## What this skill is for

In-app tours guide a PostHog _user_ (a person logged into PostHog) through a new or non-obvious feature inside the PostHog app — popovers anchored to UI elements, with a Next/Prev/Skip flow, gated by a feature flag, dismissible per user.

This is **not** the same as the customer-facing Product Tours product
(`products/product_tours/`, toolbar-authored, rendered by posthog-js on customer sites).
If the user means that, point them at `products/product_tours/ARCHITECTURE.md` instead.

## Step 0 — check for existing infra before scaffolding

Before building anything, look for an in-app tour framework that may already exist:

```sh
# reusable component
ls frontend/src/lib/components/InAppTour 2>/dev/null
ls frontend/src/lib/components/ProductTour 2>/dev/null
ls frontend/src/lib/components/Walkthrough 2>/dev/null

# reusable logic
grep -rE "inAppTourLogic|walkthroughLogic|guidedTourLogic" frontend/src/lib --include="*.ts" -l
```

If a framework exists, **reuse it** — only add a new tour config + flag.
If nothing exists, scaffold the framework once (Step 2), then add tours on top of it (Step 3).

Do **not** confuse `frontend/src/scenes/product-tours/` with an in-app tour framework — that scene is the management UI for the customer-facing Product Tours product.

## Step 1 — gather requirements from the user

Before writing code, ask the user:

1. **Goal of the tour** — what should the user be able to do or understand by the end?
   (e.g. "create their first dashboard", "find the new SQL editor", "understand the alerts panel")
2. **Steps** — for each step:
   - What UI element does the step anchor to? (CSS selector or `data-attr`)
   - What does the step say? (title + body, kept short)
   - What action ends the step? (Next click / user clicks the target element / both)
3. **Audience and rollout** — who should see it?
   (new users only? all users on a plan? % rollout? specific orgs?) → drives feature flag rules
4. **Where it appears** — which scene/route does the tour live in?
   (e.g. `frontend/src/scenes/dashboard/Dashboards.tsx`)
5. **Auto-launch vs. manual trigger** — should it open automatically the first time the scene is visited, or only when the user clicks "Show me how"?

Block on these answers. Don't guess steps or selectors.

## Step 2 — scaffold the reusable framework (only if it doesn't exist)

The framework has three pieces. Build them once; every future tour reuses them.

### Files to create

```text
frontend/src/lib/components/InAppTour/
    InAppTour.tsx              # renderer — the only component scenes mount
    InAppTourSpotlight.tsx     # darkened backdrop with cutout around the target element
    inAppTourLogic.ts          # kea logic, keyed by tourKey
    inAppTourTypes.ts          # TourStep, TourConfig types
    inAppTourRegistry.ts       # exported registry: tourKey -> TourConfig + flag key
    index.ts
```

### Reuse, don't rebuild

| Concern              | Use                                                                                                                                                                                          |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Floating positioning | `Popover` from `lib/lemon-ui/Popover`                                                                                                                                                        |
| Buttons (Next/Skip)  | `LemonButton` from `@posthog/lemon-ui`                                                                                                                                                       |
| Feature flag gating  | `featureFlagLogic` from `lib/logic/featureFlagLogic` + `FEATURE_FLAGS` from `lib/constants`                                                                                                  |
| Per-user dismissal   | kea reducer with `{ persist: true }` (mirrors `lemonBannerLogic`); for cross-device persistence, set a person property `$in_app_tour_completed/{tourKey}` via `posthog.capture('$set', ...)` |
| Analytics            | `eventUsageLogic` or direct `posthog.capture` with `in_app_tour_*` event names matching the existing `ProductTourEventName` enum style                                                       |

### Component contract

```tsx
// scene usage
<InAppTour tourKey="alerts-intro" />
```

`InAppTour` should:

1. Read the tour config from `inAppTourRegistry[tourKey]`.
2. Read `featureFlagLogic.featureFlags[config.flagKey]` — render `null` if flag is off.
3. Read `inAppTourLogic({ tourKey })` for `currentStepIndex`, `isDismissed`, `isCompleted`.
4. Render `null` if dismissed or completed.
5. Look up `document.querySelector(currentStep.selector)` — if missing, log a warning and advance / dismiss (mirror SDK behavior in `products/product_tours/ARCHITECTURE.md` "Selector not found").
6. Render `<Popover>` anchored to that element with the step content + Next / Skip / Prev buttons.
7. Render `<InAppTourSpotlight>` for the darkened cutout.

### Logic contract

`inAppTourLogic` should be keyed by `tourKey` so multiple tours coexist without state collisions. Actions: `nextStep`, `prevStep`, `dismiss`, `complete`, `restart`. Persist `isDismissed` / `isCompleted` so the tour doesn't reappear.

### Tour config shape

```ts
// inAppTourTypes.ts
export interface TourStep {
  selector: string // CSS selector or [data-attr="..."]
  title: string
  body: string | JSX.Element
  placement?: 'top' | 'bottom' | 'left' | 'right'
  advanceOn?: 'next-button' | 'target-click'
}

export interface TourConfig {
  tourKey: string // stable, kebab-case, used in flag + persistence keys
  flagKey: FeatureFlagKey // gate from FEATURE_FLAGS
  goal: string // human-readable, captured in analytics
  steps: TourStep[]
  autoLaunch?: boolean // open on mount when flag is on and not yet seen
}
```

## Step 3 — add the actual tour

For every new tour:

1. **Add a feature flag key** to `frontend/src/lib/constants.tsx`:

   ```ts
   IN_APP_TOUR_<NAME>: 'in-app-tour-<name>',
   ```

2. **Create the tour config** at `frontend/src/lib/components/InAppTour/tours/<tourKey>.ts` and register it in `inAppTourRegistry.ts`.
3. **Mount the renderer** in the scene the tour belongs to:

   ```tsx
   <InAppTour tourKey="<tourKey>" />
   ```

4. **Add `data-attr` attributes** to the elements the tour anchors to. Prefer stable `data-attr="..."` over class-name selectors — class names churn.
5. **Create the flag in PostHog** (production project) with the rollout the user described. Until the flag is on, the tour is invisible.

## Don't

- Don't add a new tour library (`react-joyride`, `intro.js`, `shepherd`, `driver.js`). Use the existing `Popover` + custom spotlight — keeps bundle size and styling consistent.
- Don't fork the renderer per tour — every tour goes through `InAppTour` + a config entry.
- Don't anchor on class names that look generated (`.css-1abc23`). Add a `data-attr` and use that.
- Don't write tour copy yourself. Get exact title/body strings from the user (or PM) — copy is a product decision.
- Don't auto-launch a tour on every render. Persist `isCompleted` / `isDismissed` per user.
- Don't use this skill for customer-facing tours rendered by posthog-js — point users at `products/product_tours/ARCHITECTURE.md`.

## Verification

- With flag off → tour does not render.
- With flag on, fresh user → tour auto-launches (if configured) and anchors to step 1.
- Resize window / scroll page → popover stays anchored (Popover handles this).
- Click Skip → tour disappears, does not return after refresh.
- Complete all steps → tour disappears, `$in_app_tour_completed/<tourKey>` set on the user.
- Selector missing in DOM → tour advances or dismisses gracefully (no broken popover dangling at 0,0).
- A second tour added later reuses `InAppTour` with no changes to the framework.
