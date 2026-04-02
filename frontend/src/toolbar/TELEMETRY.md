# Toolbar telemetry events

All events are sent via `toolbarPosthogJS`, the toolbar's internal PostHog instance,
unless noted otherwise. Events go to PostHog's internal project (prod) or `localhost:8000` (dev).

## Lifecycle

### `toolbar loaded`

Fired once when the toolbar finishes initialization.

| Property                   | Type                                   | Description                                                                    |
| -------------------------- | -------------------------------------- | ------------------------------------------------------------------------------ |
| `is_authenticated`         | `boolean`                              | Whether the user had valid tokens at load time                                 |
| `source`                   | `'url' \| 'localstorage' \| 'unknown'` | Whether the toolbar was launched from PostHog or auto-loaded from localStorage |
| `ui_host`                  | `string`                               | Resolved PostHog UI host                                                       |
| `api_host`                 | `string`                               | Resolved API host                                                              |
| `ui_host_explicit`         | `boolean`                              | Whether `uiHost` was explicitly provided in toolbar params                     |
| `ui_host_matches_api_host` | `boolean`                              | Whether UI and API hosts are the same                                          |
| `load_duration_ms`         | `number \| undefined`                  | Time from `ph_load_toolbar` call to initialization complete                    |

**File:** `toolbarConfigLogic.ts`

### `toolbar ui host check`

Fired after the CORS reachability check to the PostHog app.

| Property           | Type              | Description                                                          |
| ------------------ | ----------------- | -------------------------------------------------------------------- |
| `ui_host`          | `string`          | Host being checked                                                   |
| `api_host`         | `string`          | API host for reference                                               |
| `ui_host_source`   | `string`          | How the UI host was resolved                                         |
| `is_authenticated` | `boolean`         | Auth state at time of check                                          |
| `status`           | `'ok' \| 'error'` | Check result                                                         |
| `error_type`       | `string`          | Only on error: `timeout`, `network_or_cors`, `http_error`, `unknown` |
| `duration_ms`      | `number`          | Time taken for the check                                             |

**File:** `toolbarConfigLogic.ts`

## Authentication

### `toolbar authenticate`

Fired when the user triggers authentication.

| Property           | Type      | Description                          |
| ------------------ | --------- | ------------------------------------ |
| `is_authenticated` | `boolean` | Auth state when action was triggered |

**File:** `toolbarConfigLogic.ts`

### `toolbar oauth exchange`

Fired after an OAuth authorization code exchange attempt.

| Property      | Type                                      | Description                               |
| ------------- | ----------------------------------------- | ----------------------------------------- |
| `status`      | `'success' \| 'error' \| 'network_error'` | Outcome of the exchange                   |
| `duration_ms` | `number`                                  | Time taken for the exchange               |
| `error`       | `string`                                  | Only on `error` status: error description |

**File:** `toolbarConfigLogic.ts`

### `toolbar token refresh`

Fired after a token refresh attempt (triggered automatically on 401 responses).

| Property      | Type                   | Description                       |
| ------------- | ---------------------- | --------------------------------- |
| `status`      | `'success' \| 'error'` | Outcome of the refresh            |
| `duration_ms` | `number`               | Time taken for the refresh        |
| `http_status` | `number`               | Only on `error`: HTTP status code |

**File:** `toolbarAuth.ts`

### `toolbar token expired`

Fired when the OAuth token expires or a 403 is received.
No properties.

**File:** `toolbarConfigLogic.ts`

### `toolbar logout`

Fired when the user logs out from the toolbar.
No properties.

**File:** `toolbarConfigLogic.ts`

### `toolbar ui host config modal opened`

Fired when the UI host configuration modal is shown (auth error state).

| Property  | Type     | Description           |
| --------- | -------- | --------------------- |
| `ui_host` | `string` | Current UI host value |

**File:** `toolbarConfigLogic.ts`

## API requests

### `toolbar api request`

Fired after every `toolbarFetch` call. Covers all toolbar API endpoints.

| Property          | Type      | Description                                        |
| ----------------- | --------- | -------------------------------------------------- |
| `method`          | `string`  | HTTP method (`GET`, `POST`, `PATCH`, `DELETE`)     |
| `pathname`        | `string`  | API path (e.g., `/api/projects/@current/actions/`) |
| `status`          | `number`  | HTTP response status code                          |
| `duration_ms`     | `number`  | Total time including any token retry               |
| `did_token_retry` | `boolean` | Whether a 401 triggered a token refresh + retry    |

**File:** `toolbarConfigLogic.ts`

## Menu and mode

### `toolbar menu opened`

Fired when a toolbar menu becomes visible.

| Property        | Type        | Description                      |
| --------------- | ----------- | -------------------------------- |
| `menu`          | `MenuState` | Menu that was opened             |
| `previous_menu` | `MenuState` | Menu that was previously visible |

**File:** `bar/toolbarLogic.ts`

### `toolbar menu closed`

Fired when a toolbar menu is closed (state returns to `'none'`).

| Property | Type        | Description          |
| -------- | ----------- | -------------------- |
| `menu`   | `MenuState` | Menu that was closed |

**File:** `bar/toolbarLogic.ts`

### `toolbar mode triggered`

Fired when a toolbar mode is toggled on or off.

| Property  | Type      | Description                                                             |
| --------- | --------- | ----------------------------------------------------------------------- |
| `mode`    | `string`  | One of: `heatmap`, `inspect`, `actions`, `experiments`, `product-tours` |
| `enabled` | `boolean` | Whether the mode was enabled or disabled                                |

**Files:** `elements/elementsLogic.ts`, `elements/heatmapToolbarMenuLogic.ts`,
`actions/actionsTabLogic.tsx`, `experiments/experimentsTabLogic.tsx`,
`product-tours/productToursLogic.ts`

## Element inspection

### `toolbar selected HTML element`

Fired when an element is selected in inspect mode.

| Property          | Type             | Description                          |
| ----------------- | ---------------- | ------------------------------------ |
| `element_tag`     | `string \| null` | HTML tag name                        |
| `element_type`    | `string \| null` | `type` attribute value               |
| `has_href`        | `boolean`        | Whether element has an href          |
| `has_class`       | `boolean`        | Whether element has classes          |
| `has_id`          | `boolean`        | Whether element has an id            |
| `has_name`        | `boolean`        | Whether element has a name attribute |
| `has_data_attr`   | `boolean`        | Whether element has data attributes  |
| `data_attributes` | `string[]`       | List of data attribute names         |

**File:** `elements/elementsLogic.ts`

## Actions

### `toolbar_manual_selector_modal_opened`

Fired when the manual CSS selector editing modal is opened.

| Property   | Type             | Description                   |
| ---------- | ---------------- | ----------------------------- |
| `selector` | `string \| null` | Current selector being edited |

**File:** `actions/ActionsEditingToolbarMenu.tsx`

### `toolbar_manual_selector_applied`

Fired when a user applies a manual CSS selector.

| Property         | Type     | Description                   |
| ---------------- | -------- | ----------------------------- |
| `chosenSelector` | `string` | The selector that was applied |

**File:** `actions/ActionsEditingToolbarMenu.tsx`

## Feature flags

### `toolbar feature flag overridden`

Fired when a feature flag override is applied.
No properties.

**File:** `flags/flagsToolbarLogic.ts`

### `toolbar feature flag override removed`

Fired when a feature flag override is removed.
No properties.

**File:** `flags/flagsToolbarLogic.ts`

### `toolbar flags impersonated`

Fired when flags are loaded for a different distinct ID.

| Property      | Type     | Description                        |
| ------------- | -------- | ---------------------------------- |
| `distinct_id` | `string` | The distinct ID being impersonated |

**File:** `flags/flagsToolbarLogic.ts`

## Product tours

### `product tour recording started`

Fired when session recording starts for product tour editing.
No properties.

**File:** `product-tours/productToursLogic.ts`

### `product tour step added`

Fired when a new step is added to a tour.

| Property     | Type             | Description                 |
| ------------ | ---------------- | --------------------------- |
| `step_type`  | `string`         | Type of step added          |
| `step_index` | `number`         | Index of the new step       |
| `tour_id`    | `string \| null` | ID of the tour being edited |

**File:** `product-tours/productToursLogic.ts`

### `product tour step removed`

Fired when a step is removed from a tour.

| Property          | Type             | Description                   |
| ----------------- | ---------------- | ----------------------------- |
| `step_type`       | `string \| null` | Type of step removed          |
| `step_index`      | `number`         | Index of the removed step     |
| `tour_id`         | `string \| null` | ID of the tour                |
| `remaining_steps` | `number`         | Steps remaining after removal |

**File:** `product-tours/productToursLogic.ts`

### `product tour consent selected`

Fired when the user selects session recording consent.

| Property  | Type      | Description               |
| --------- | --------- | ------------------------- |
| `consent` | `boolean` | Whether consent was given |

**File:** `product-tours/productToursLogic.ts`

### `product tour preview started`

Fired when the user starts previewing a product tour.

| Property     | Type             | Description                    |
| ------------ | ---------------- | ------------------------------ |
| `tour_id`    | `string \| null` | ID of the tour being previewed |
| `step_count` | `number`         | Number of steps in the tour    |

**File:** `product-tours/productToursLogic.ts`

## Screenshots

### `media preview uploaded`

Fired after a successful screenshot/media upload.

| Property | Type        | Description        |
| -------- | ----------- | ------------------ |
| `source` | `'toolbar'` | Always `'toolbar'` |

**File:** `screenshot-upload/screenshotUploadLogic.ts`

## Heatmap sampling (page's PostHog instance)

These events use the **page's** `posthog.capture()`, not `toolbarPosthogJS`.
They are sent to the customer's project, not PostHog's internal project.

### `sampling_enabled_on_heatmap`

Fired when sampling is enabled on the heatmap. No properties.

### `sampling_disabled_on_heatmap`

Fired when sampling is disabled on the heatmap. No properties.

### `sampling_percentage_updated_on_heatmap`

Fired when the sampling percentage is changed.

| Property         | Type     | Description                                |
| ---------------- | -------- | ------------------------------------------ |
| `samplingFactor` | `number` | New sampling factor (e.g., 0.1, 0.25, 0.5) |

**File:** `stats/HeatmapToolbarMenu.tsx`
