---
name: creating-customer-analytics-account-widgets
description: >
  Creates or changes a Customer analytics account widget: a tile on an account detail view, or an
  account detail tab. Use when adding a widget, tile, or tab to the account page, giving a widget saved
  settings or a settings editor, or reviewing a diff that touches accountViewComponents.tsx,
  AccountViewComponent, AccountViewTile, AccountViewTileEditorModal, or account_views.py. Account view
  widgets follow the composition pattern: each widget is one entry in the ACCOUNT_VIEW_COMPONENTS
  registry, and shared code never branches on a widget kind. Covers the registry entry, the widget props
  contract, saved tile config, the backend tag and config validator, system tabs, and feature flags.
---

# Creating Customer analytics account widgets

Account view widgets follow the composition pattern.
A view is an ordered list of independent widgets.
Shared code knows a widget only through its entry in `ACCOUNT_VIEW_COMPONENTS`.
The [Accounts guide](../../../products/customer_analytics/frontend/components/Accounts/AGENTS.md#account-view-widgets) states the rules. Read that section first. This skill holds the steps.

Paths below are relative to `products/customer_analytics/`.

## The rule that decides most questions

Do not add a `kind ===` branch to shared code.
Shared code is `AccountViewComponent`, `AccountViewTile`, `AccountViewTileEditorModal`, `AccountViewRenderer`, `accountViewsLogic`, and `validate_account_view_content`.
When a widget needs something the others do not, add an optional field to `AccountViewComponentBase` and let shared code read it.
`ConfigEditor`, `getConfigError`, `onConfigSaved`, and `tileInsetClassName` are the precedent.

## Decide first

- **Tile only, or also a tab?** A tile-only widget has no `systemTabId`. A tab also appears in the account detail tabs.
- **Does it save settings?** If the widget has a filter, search, or sort worth keeping, it reads and writes tile config.
- **Does it need a settings editor?** Only when the tile's own controls cannot set the config. Properties and SQL query are the precedents.
- **Is it flag-gated?** Ask the user. Do not invent a flag.

## Steps

1. **Build the widget.** Put the component and its logic in `frontend/components/Accounts/`. Model them on `AccountMeetingsExpansion` and `accountMeetingsLogic`. Key the logic by account and `instanceId`, as in `` `${props.accountId}:${props.instanceId ?? 'default'}` ``. Without `instanceId`, two tiles of one kind share state.
2. **Add the kind.** For a tile-only widget, add it to both unions in `accountViewComponents.tsx`. For a tab, see [Tabs](#tabs).
3. **Add the registry entry.** Set `kind`, `tagName`, `label`, and `Component`. `Component` takes `AccountViewWidgetProps` and maps them to the widget. Pass `getTileLogicProps(props)` when the widget saves settings.
4. **Add the tag to the backend.** Add `tagName` and its label to `ACCOUNT_VIEW_COMPONENT_LABELS` in `backend/logic/account_views.py`. Without it, the API rejects every view that holds the widget.
5. **Add the test rows.** Add the tag to the parameterized `test_accepts_account_widget` in `backend/test/test_account_views.py`. Invoke `/writing-tests` before you add anything more.
6. **Update the Accounts guide.** It asks for this in the same change.

## Saved settings

- The widget's logic reads `props.initialConfig` once, as reducer defaults. Use `getTileString`, `getTileStringArray`, and `getTileRecord` from `accountViewTileConfig.ts`, because saved config is untyped and can be stale.
- The logic calls `props.onConfigChange?.(config)` from a listener with the whole config, not a patch. A read-only viewer gets no `onConfigChange`.
- **Config never holds an account identity.** A view is reused across accounts, so the backend rejects `accountId`, `externalId`, `projectId`, `teamId`, and their snake_case forms at any depth. It also rejects config over 16 KB.
- If bad config can break the widget, add a validator to `ACCOUNT_VIEW_CONFIG_VALIDATORS`, keyed by `tagName`. `validate_properties_widget_config` is the model.

## Settings editor

Add `ConfigEditor` to the entry. It takes `AccountViewTileConfigEditorProps` and does not save. `AccountViewTileEditorModal` renders it under the tile name, and `accountViewsLogic.saveTileEditor` saves the name and the config in one queued write.
To block a save on bad config, add `getConfigError` to the entry. It returns the reason, and the modal shows that reason on the save button.
To track a save, add `onConfigSaved` to the entry. Do not capture the event in `accountViewsLogic`.

## Tabs

A tab needs these on top of the steps above:

- Add the kind to `AccountExpansionTab` and `ACCOUNT_EXPANSION_TABS` in `accountsExpansionLogic.ts`.
- Set `systemTabId: 'system:<kind>'` on the entry.
- Add the same id to `ACCOUNT_DETAIL_SYSTEM_TAB_IDS` in `backend/logic/user_customer_analytics_config.py`. Without it, a user cannot save the tab's order or visibility.

## Feature flags

Set `featureFlag` on the entry. That hides the widget from the picker, the renderer, and the tabs.
A flag-gated tab also needs a line in `getVisibleAccountExpansionTab`, so a direct link falls back to the default tab.
Extend the flag cases in `accountTabs.test.ts` and `AccountViewRenderer.test.tsx`.

## Frozen strings

`tagName` is stored in every saved view. `systemTabId` is stored in every user's tab settings.
Never rename either one. A renamed `tagName` drops the tile from saved views without an error.

## Before you report done

- No shared file gained a `kind ===` or `tag_name ==` branch.
- The widget renders as a tile at a narrow span, and as a tab if it has `systemTabId`.
- Two tiles of the new kind on one view keep separate state.
- Saved settings survive a reload, and a read-only viewer triggers no write.
- The backend accepts a view that holds the new tag.
