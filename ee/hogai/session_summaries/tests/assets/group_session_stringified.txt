# Patterns

## Pattern: Pay-gate Blocks Core Settings (critical)
Users trying to reach project or environment settings are shown a pay-gate and leave without upgrading, cutting short deeper engagement and any chance of conversion.

### Potential indicators
- Event "pay gate shown" triggered while user is on settings-related URLs (e.g., /settings/project, /settings/environment)
- No subsequent "upgrade", "plan selected", or billing page visit before session end
- Session outcome marked unsuccessful with abandonment flagged in same segment as the pay gate
- User attempts to access the gated page again within the same session (more than 1 navigation to the same settings area) before giving up

### Session examples

#### Session `0197e8d5-6eb2-79b6-95bf-5a5ba11edbfa` - Segment #2
Entered settings, hit paywall, and exited

**Key event:**
- Issues noticed: abandonment, confusion. Paywall displayed repeatedly, blocking desired settings at 00:00:45, as "pay gate shown" event (event_uuid: `0197e8d6-2490-7cbc-96f1-f60012051e4b`).

**Before it:**
- Clicked Settings link from sidebar at 00:00:45, as "$autocapture" (click) event (event_uuid: `0197e8d6-2490-7cbc-96f1-f60012051e4b`).

**After it:**
- Navigated to Integrations page then became idle at 00:00:48, as "$pageview" event (event_uuid: `0197e8d6-2490-7cbc-96f1-f60012051e4b`).

**Outcome:**
Failure. Paywall blocked deeper settings; user did not upgrade and eventually left.

#### Session `0197e8d5-5a41-7628-8954-ab652f7afed0` - Segment #2
Explore view settings – blocked by first pay-gate

**Key event:**
- Issues noticed: abandonment. First pay gate appears when opening settings panel at 00:04:59, as "pay gate shown" event (event_uuid: `0197e8d9-ea0b-79c4-8574-81e21cc8036e`).

**Before it:**
- User retries by clicking Reload but remains in limited view at 00:04:28, as "$autocapture" (click) event (event_uuid: `0197e8d9-ea0b-79c4-8574-81e21cc8036e`).

**After it:**
- Nothing, end of the segment.

**Outcome:**
Failure. Settings exploration halted by first pay gate.

#### Session `0197e8d5-5a41-7628-8954-ab652f7afed0` - Segment #3
Navigate to Insights & environment settings – second pay-gate

**Key event:**
- Issues noticed: abandonment. Second pay gate blocks environment settings page at 00:07:01, as "pay gate shown" event (event_uuid: `0197e8db-c58c-72e6-b6cd-d3c263754943`).

**Before it:**
- Sidebar navigation to Product Analytics (Insights) at 00:06:34, as "$autocapture" (click) event (event_uuid: `0197e8db-c58c-72e6-b6cd-d3c263754943`).

**After it:**
- Nothing, end of the segment.

**Outcome:**
Failure. Insights opened but environment settings blocked again by pay gate.

#### Session `0197e8d5-5a41-7628-8954-ab652f7afed0` - Segment #6
Return to Activity & Live – frustration and project settings pay-gate

**Key event:**
- Issues noticed: abandonment. Pay gate shown on Project Settings page at 00:14:31, as "pay gate shown" event (event_uuid: `0197e8e2-a2e9-7081-8e0f-37c961e74796`).

**Before it:**
- Issues noticed: confusion. Rage-clicks on “AlloTools” list item indicating frustration at 00:14:24, as "$rageclick" (click) event (event_uuid: `0197e8e2-a2e9-7081-8e0f-37c961e74796`).

**After it:**
- Issues noticed: confusion. Dead click followed by copying validation message at 00:15:37, as "$dead_click" (click) event (event_uuid: `0197e8e2-a2e9-7081-8e0f-37c961e74796`).

**Outcome:**
Failure. Live view frustration and yet another pay gate ended session.

## Pattern: Frustration Click Loops (high)
After hitting a blocker or unclear UI state, users repeatedly click or toggle the same element (rage-clicks, rapid checkbox switches, reload spamming), signalling confusion and potential churn.

### Potential indicators
- "$rageclick" or "$dead_click" events recorded on the same target element
- "confusion": true on multiple consecutive events within a 10-second window
- More than 3 identical clicks/toggles on the same control without state change (e.g., checkbox rapidly on/off, repeated Reload button presses)
- Frustration sequence followed by idle time or session exit without completing intended task

### Session examples

#### Session `0197e8d5-6f25-7310-a1d9-00f7557f4b8f` - Segment #0
Initial price-calculator setup

**Key event:**
- Issues noticed: confusion. Rapidly toggled Website analytics checkbox multiple times at 00:01:05, as "$autocapture" (click) event (event_uuid: `0197e8d6-6ff4-7abf-861b-58ed46233c10`).

**Before it:**
- Changed monthly event volume input at 00:00:59, as "$autocapture" (click) event (event_uuid: `0197e8d6-6ff4-7abf-861b-58ed46233c10`).

**After it:**
- Opened “explain event types” help section at 00:01:11, as "$autocapture" (click) event (event_uuid: `0197e8d6-6ff4-7abf-861b-58ed46233c10`).

**Outcome:**
Success. Customized initial pricing inputs, brief checkbox indecision resolved quickly.

#### Session `0197e8d5-5a41-7628-8954-ab652f7afed0` - Segment #6
Return to Activity & Live – frustration and project settings pay-gate

**Key event:**
- Issues noticed: confusion. Rage-clicks on “AlloTools” list item indicating frustration at 00:14:24, as "$rageclick" (click) event (event_uuid: `0197e8e2-8626-796a-8711-41f657435816`).

**Before it:**
- Nothing, start of the segment.

**After it:**
- Issues noticed: abandonment. Pay gate shown on Project Settings page at 00:14:31, as "pay gate shown" event (event_uuid: `0197e8e2-8626-796a-8711-41f657435816`).
- Issues noticed: confusion. Dead click followed by copying validation message at 00:15:37, as "$dead_click" (click) event (event_uuid: `0197e8e2-8626-796a-8711-41f657435816`).

**Outcome:**
Failure. Live view frustration and yet another pay gate ended session.

#### Session `0197e8d5-5a41-7628-8954-ab652f7afed0` - Segment #6
Return to Activity & Live – frustration and project settings pay-gate

**Key event:**
- Issues noticed: confusion. Dead click followed by copying validation message at 00:15:37, as "$dead_click" (click) event (event_uuid: `0197e8e3-b0eb-7a2b-be7d-d040d686ee19`).

**Before it:**
- Issues noticed: confusion. Rage-clicks on “AlloTools” list item indicating frustration at 00:14:24, as "$rageclick" (click) event (event_uuid: `0197e8e3-b0eb-7a2b-be7d-d040d686ee19`).
- Issues noticed: abandonment. Pay gate shown on Project Settings page at 00:14:31, as "pay gate shown" event (event_uuid: `0197e8e3-b0eb-7a2b-be7d-d040d686ee19`).

**After it:**
- Nothing, end of the segment.

**Outcome:**
Failure. Live view frustration and yet another pay gate ended session.