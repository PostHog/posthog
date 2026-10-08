---
name: styling-sidebar-products
description: >
  How products and pages appear in the PostHog sidebar: which category they sit in, which icon and color they
  get, and which groups share a color gradient. Use when adding a product or data management page to the
  sidebar (treeItemsProducts or treeItemsMetadata in a products/*/manifest.tsx), giving an entry a new icon or
  color, moving an entry between sidebar categories, adding a category, or when a sidebar icon renders the
  wrong color, the wrong glyph, or differently once starred. Trigger terms: sidebar, nav, All products,
  Popular, category, iconType, iconColor, product icon, product color, gradient, starred icon.
---

# Styling sidebar products

The sidebar reads every entry from the product manifests.
An entry needs three things to look right: a category, an icon type that only it uses in the sidebar, and a color.
Some categories share a gradient, so a new entry in one of them changes its neighbors' colors too.

## Where things live

| What                                                                           | File                                                                                  |
| ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------- |
| Entry definition (`path`, `category`, `iconType`, `iconColor`, `href`, `flag`) | `products/<product>/manifest.tsx`, under `treeItemsProducts` or `treeItemsMetadata`   |
| Icon glyph and default color per icon type                                     | `iconTypes` in `frontend/src/layout/panel-layout/ProjectTree/defaultTree.tsx`         |
| The icon type union                                                            | `FileSystemIconType` in `frontend/src/queries/schema/schema-general.ts`               |
| Color values                                                                   | `--color-product-<name>-light` and `-dark` in `frontend/src/styles/base.scss`         |
| Category names                                                                 | `ProductItemCategory` in `schema-general.ts`                                          |
| Category order in the sidebar                                                  | `CATEGORY_ORDER` in `frontend/src/layout/panel-layout/navbar/tabs/productsCatalog.ts` |
| Sidebar-only groupings (Popular, hidden tab pages, pinned rows)                | `navProductsTabLogic.ts` and `productsCatalog.ts` in the same folder                  |
| Custom icons that are components, like the Support badge                       | `ProjectTree/customIconRegistry.tsx`                                                  |

## Rules

**One icon per entry.** No two sidebar entries share a glyph.
If the icon type you want is also used outside the sidebar, for example `event_definition` or `data_pipeline_metadata`, add a new icon type instead of changing the shared one.
A new icon type goes into the `FileSystemIconType` union and the `iconTypes` map, and then `hogli build:schema` regenerates the Python enums.

**One color, set in both places.** Put the same color variable pair on the `iconTypes` entry and on the manifest entry's `iconColor`.
The sidebar row uses the manifest color. Scene titles, search and other surfaces use the map color.
When the two disagree, the product shows two colors across the app.
Always give both a light and a dark variable, because a single value is reused for dark mode and reads poorly there.

**Starred entries follow the product.** A star stores only `iconType || type` and `href`.
The file tree looks up the product by `href` (`getProductIcon` in `defaultTree.tsx`) and uses its icon and color, and it wraps custom icons in `ProductIconWrapper`.
Do not add a per-surface icon override. Fix the manifest and the map, and the star follows.

**Pinned rows stay neutral.** Home, Self-driving and Activity and people have no color on purpose.

## Color families

Four categories use one gradient each. The steps follow the order the sidebar shows, which is alphabetical by label.

| Category       | Gradient                      | Light end points                       |
| -------------- | ----------------------------- | -------------------------------------- |
| AI engineering | indigo to magenta             | `rgb(99 102 241)` to `rgb(196 60 218)` |
| CDP            | golden yellow to burnt orange | `rgb(234 179 8)` to `rgb(194 65 12)`   |
| Schema         | teal to deep blue             | `rgb(20 184 166)` to `rgb(29 78 216)`  |
| Tools          | red to magenta pink           | `rgb(239 68 68)` to `rgb(217 40 160)`  |

When you add, remove or rename an entry in one of these categories, regenerate the whole category, since every step moves:

```sh
python3 .agents/skills/styling-sidebar-products/scripts/sidebar_gradient.py schema \
    actions annotations event-definitions mcp-servers sql-variables
```

Pass the color variable names in sidebar order, and include entries behind a feature flag.
Paste the output over the matching lines in `base.scss`.
If an entry shared a variable with a product outside the group, give it its own variable first. `warehouse-destinations` is an example: it used to share with Data ops.
The end points, including dark mode, live in the script. Change them there, not by hand in `base.scss`.

The other categories (Popular, Data, Monitoring, Product engineering, Messaging, Unreleased) use each product's own brand color.
Pick a hue that differs from the entries right next to it in the same category.
Avoid the gradient families above, so a product does not look like it belongs to AI engineering, CDP, Schema or Tools.

## Categories

Categories are values of `ProductItemCategory`, and the backend reads them through `products.json`.
After renaming or adding one, update `CATEGORY_ORDER` in `productsCatalog.ts`, update the old nav's `CATEGORY_ORDER` in `ProjectTree/utils.tsx`, and update `test_get_products_by_category_has_expected_categories` in `posthog/test/test_products.py`.
Then run `hogli build:schema` and `pnpm --filter=@posthog/frontend build:products`.

Popular is sidebar-only. It lives in `POPULAR_PRODUCT_PATHS` and does not change a product's real category.
Pages that are tabs of another page, like the definitions tabs, stay in their manifest but are hidden in `navProductsTabLogic.ts`.

## Check it

- `hogli test frontend/src/layout/panel-layout` runs the sidebar logic tests. It also checks that every starred product renders the same icon and color as its row, in `ProjectTree/utils.test.ts`.
- Render the `Layout/Products and files` story in light and dark (`Dark` story), and look at the whole category, not only the new entry. A gradient reads wrong when one step is off.
- Storybook does not hot-reload `base.scss`. Restart it after changing a color, or it keeps rendering the old values.
- Neighboring steps need visible contrast. When steps look alike, widen the end points in hue and lightness rather than adding more steps.
