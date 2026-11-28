---
name: adding-dashboard-v2-custom-content
description: >
  Guides putting a product's own React component in a dashboards v2 tile through the custom panel type:
  a content package in the product's folder (`defineContentPackage`), `createCustomPanel({ packages })`,
  the off-by-default opt-ins (`movable`, `menuActions`, `showOnInteractiveOnly`) and reading or changing
  the dashboard's filters. Use when migrating an existing component, banner, list or prompt from a product
  page into a dashboards v2 tile, adding a new custom content, or reviewing a diff that touches a content
  package. Not for a new kind of chart or panel type (`adding-dashboard-v2-panel-types`).
---

# Adding custom content to a dashboards v2 tile

A custom content is a product's own React component shown in a tile.
The tile draws the frame (title, menu, error boundary), and the document saves only the content's name, such as `{ type: 'custom', config: { content: 'web-analytics/browser-filter' } }`.
Read `products/dashboards_v2/.agents/composing.md` ("Your own component in a tile") and `.agents/primitives.md` first.

## Decide it is custom content

- The component draws the result of a query as a chart, number or table: make it a chart kind instead, as `composing.md` describes in "Your own kind of chart". Charts get sample data, filters, image export and the chart menu for free.
- It is not a query result, or it needs its own interaction, such as a setup prompt, a checklist, a list with actions or a control that changes the dashboard's filters: make it custom content.

## Migrate a component

1. **Find or create the product's package.** One per product, in that product's own folder, such as `products/web_analytics/frontend/dashboard/webAnalyticsContents.ts` (use `/placing-product-frontend-code` when unsure).
   The namespace is the product's name in kebab case. It is saved in every document that uses the content, so pick it once and never rename it.
2. **Add the content with a short name.**

   ```ts
   const BrowserFilter = lazy(() => import('./BrowserFilter').then((module) => ({ default: module.BrowserFilter })))

   export const webAnalyticsContents = defineContentPackage('web-analytics', {
     'browser-filter': { Component: BrowserFilter, size: { w: 8, h: 8, minW: 6, minH: 6 } },
   })
   ```

   Load the component with `React.lazy`, so code that only checks documents never loads it. The name is saved in documents too: renaming one breaks saved dashboards.

3. **Decide what the tile sets.** A value that differs between two tiles of the same content, such as which service a list shows, is a prop: wrap the content in `defineContent` with a `propsSchema` (a `z.strictObject`), and the tile saves the values in `config.props`. The prop names are saved in documents, so renaming one breaks saved dashboards. Everything else is not a prop:
   - Data it loaded from its scene's props or logic comes from a logic keyed on what the component can read itself, such as the current team.
   - The dashboard's time range and filters come from `FiltersContext`.
   - A control that changes them uses the controllers in `FilterControlsContext`. Each is missing when the dashboard has none, so disable the control with a `disabledReason` then.
   - Never read `DashboardStateContext` or a context from the page the component came from.
4. **Strip its own frame.** Remove the component's card, border, padding that matches the card's, and its title. The tile draws them, and the tile's `title` holds the heading. Hide the tile header with `parts: { header: false }` when the content has its own, such as a callout.
5. **Fill the tile.** The content gets the tile's height. A list or table scrolls inside itself, and nothing sets a fixed height. Pick `size` so the default tile shows the content without a scrollbar.
6. **Give it a `Loading`** shaped like the content when it loads data, so an off-screen tile looks like itself. Left out, the tile shows the default loading state.
7. **Opt in only to what the product wants people to do.** By default a content cannot be moved and has an empty menu.
   - `movable: true` lets a person drag, resize, move and remove the tile.
   - `menuActions(actions, context)` returns the built-in actions to show, such as `actions.filter((action) => action.key === 'download-image')`. Left out, the menu is empty.
   - `keepMounted: true` keeps the component mounted after it scrolls out of view. Set it when the component holds state a person would lose, such as a picked tab or a draft, and leave it out otherwise, because the tile then stays in memory.
   - `showOnInteractiveOnly: true` leaves the tile out of images and printed pages. Use it for prompts, buttons and live counters, which mean nothing in a snapshot.
8. **Register the package** in the host's panel list, `createCustomPanel({ packages: [webAnalyticsContents] })`, and add the tile to the dashboard JSON. A product page passes only its own package: products never import another product's package.

## Before you report done

- The tile renders on the host page, with no "not valid" message and no scrollbar at its default size.
- A content with a `propsSchema` renders from the props its tile saved, and a tile with a wrong prop shows the "not valid" message.
- Every control works and changes the dashboard's filters or time range when it should.
- The tile has no drag handle or menu entries unless the content opted in.
- An image download leaves out the content when `showOnInteractiveOnly` is set.
- The old component's other callers still work, or were moved to the content.
- `pnpm --filter=@posthog/frontend typescript:check` and the touched Jest tests pass.
