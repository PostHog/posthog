# Slack block selection

Sources checked: 2026-10-26. Recheck current limits and supported surfaces before implementation.

## Upstream design reference

Slack maintains the [block-kit skill](https://github.com/slackapi/slack-skills-plugin/blob/main/skills/block-kit/SKILL.md), [design principles](https://github.com/slackapi/slack-skills-plugin/blob/main/skills/block-kit/references/design-principles.md), and [data-display guide](https://github.com/slackapi/slack-skills-plugin/blob/main/skills/block-kit/references/data-display-design.md).
Use those sources for general block selection. This reference provides a component comparison, not a replacement schema.

Validate resolved payloads with [blocks.validate](https://docs.slack.dev/reference/methods/blocks.validate/).
A successful validation does not establish surface support, count limits, initial expansion, or action behavior.

## Blocks and their purpose

| Block            | Good fit                                                                 | Constraints and checks                                                                                                                                                                                  |
| ---------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `card`           | Compact linked result, short summary, navigation buttons                 | Title and subtitle: 150 characters each. Body and subtext: 200 each. Maximum three action buttons. Keep long summaries and menus outside.                                                               |
| `container`      | Summary or report group with a heading and several child blocks          | Maximum ten child blocks. Width supports `full`. Use `is_collapsible: false` for essential content. Do not nest it in legacy attachments without a real API check.                                      |
| `section.fields` | Related label/value pairs                                                | Two-column presentation, maximum ten fields, 2,000 characters per field. Check narrow rendering.                                                                                                        |
| `section`        | Short explanation, optionally with an accessory                          | Text maximum 3,000 characters. `expand` controls text expansion; verify behavior for the app and surface.                                                                                               |
| `markdown`       | Longer generated report with headings, lists, code, or tables            | Standard Markdown. Cumulative 12,000 characters per payload. Slack may translate it into several blocks. Image syntax produces links, so use a separate chart block. Verify app support and safe links. |
| `rich_text`      | Formatted prose with literal dynamic values and explicit link boundaries | Keep element styles explicit. Use the styles supported by each element.                                                                                                                                 |
| `image`          | Chart, photograph, or illustration                                       | Provide useful alternative text. A Slack file reference needs file access for the viewer. Do not shrink a chart into an accessory merely to fit a card.                                                 |
| `actions`        | Buttons and menus                                                        | Preserve interaction identifiers and menu choices when editing a payload. Do not assume card actions accept the same elements.                                                                          |
| `context`        | Secondary attribution or source details                                  | Keep critical values and required actions in the main content.                                                                                                                                          |
| `alert`          | Colored informational or warning banner in a modal                       | Slack documents this block as modal-only. Do not copy it into a channel message.                                                                                                                        |
| `task_card`      | A real task or investigation step, with details, output, and sources     | States are `in_progress`, `complete`, and `error`. An ongoing state needs an update path.                                                                                                               |
| `carousel`       | Optional compact source or result cards                                  | Do not hide required findings, charts, or controls behind horizontal navigation.                                                                                                                        |

| `table` | Small comparison or report with repeated rows | Up to 100 rows and 20 columns; 10,000 characters across table cells per message. Supports rich-text, raw-text, and raw-number cells, column alignment, and wrapping. |
| `data_table` | Repeated rows that need sorting, pagination, filtering, or row actions | Required caption and header row; up to 200 data rows plus header, 20 columns, and 20,000 characters across table cells per message. Default page size is five. Use numeric cells for numeric sorting. |

Card text fields use text objects in Slack's examples, despite the reference table describing them as strings.
Card `actions` is an array of buttons in the example payload. Check the actual example and API, not only the field table.

## Choose prose, fields, or a table

- For one finding, use a short sentence with selective emphasis. A table or scattered label/value columns adds work for the reader.
- For independent metadata, use paired fields when the narrow layout remains readable.
- For several comparable items, compare `table` and `data_table` with the same data.
- Prefer `table` when all rows should be easy to scan without paging or row actions.
- Consider `data_table` when sorting, paging, filtering, or a row action helps the task.
- Keep the most important finding visible outside a paginated table. Its default five-row page can hide other results.
- Keep numbers numeric for sorting; do not use a rich-text code cell if it changes numeric sorting into alphabetical sorting.
- Data-table header cells cannot use `rich_text`. Action cells require buttons and can provide a text or number fallback.
- Action cells are specific to `data_table`. Copied or shared data-table action buttons are disabled.
- Check API acceptance, supported surface, desktop and narrow rendering, and action handling separately.

The table comparison is based on Slack's references. It is not proof that either component passed a live application delivery test.

## Patterns from Slack's templates

Inspect the current [template gallery](https://app.slack.com/block-kit-builder/templates) when a visual example helps.

- **Deep Research Result:** opening section, native Markdown report, source cards in a carousel, secondary context.
  Use its report hierarchy for investigation results. Keep required evidence visible outside a carousel.
- **Markdown Preview:** headings, emphasis, tables, lists, task lists, code, quotations, and links in a native Markdown block.
  Use it to check text conversion. A rendering demonstration does not establish a safe link policy.
- **Notification with Actions:** card title, subtitle, short body, action buttons, then context.
  Use it for a short result with context and a few actions. Keep longer content outside the card.
- **Itinerary:** header, dividers, paired fields, labeled groups, and short sections.
  The supplied template is a modal. Its section and field pattern can also inform messages with supported blocks.
- **Alerts:** alert banners and compact cards separated by dividers.
  The supplied template is a modal. Reuse the hierarchy in messages, but not its modal-only alert block.

## Official references

- [Card](https://docs.slack.dev/reference/block-kit/blocks/card-block/)
- [Container](https://docs.slack.dev/reference/block-kit/blocks/container-block/)
- [Container fields in the official Python SDK](https://docs.slack.dev/tools/python-slack-sdk/reference/models/blocks/blocks.html)
- [Section and expansion](https://docs.slack.dev/reference/block-kit/blocks/section-block/)
- [Markdown](https://docs.slack.dev/reference/block-kit/blocks/markdown-block/)
- [Alert and surface restriction](https://docs.slack.dev/reference/block-kit/blocks/alert-block/)
- [Task card](https://docs.slack.dev/reference/block-kit/blocks/task-card-block/)
- [Task streaming and display modes](https://docs.slack.dev/changelog/2026/02/11/task-cards-plan-blocks/)

- [Simple table](https://docs.slack.dev/reference/block-kit/blocks/table-block/)
- [Data table](https://docs.slack.dev/reference/block-kit/blocks/data-table-block/)

## Sources and attribution

This skill adapts the workflow in Slack's official [Block Kit skill](https://github.com/slackapi/slack-skills-plugin/blob/main/skills/block-kit/SKILL.md), including surface selection, live schema discovery, modification preservation, validation, and visual checks.
Its selection guidance also draws on Slack's [design principles](https://github.com/slackapi/slack-skills-plugin/blob/main/skills/block-kit/references/design-principles.md) and [data-display guide](https://github.com/slackapi/slack-skills-plugin/blob/main/skills/block-kit/references/data-display-design.md).
Reviewed revision: `2c95c4c0fc03a81bb0f15da802ed754dc6d46a8f`, 2026-10-26.
The local workflow is self-contained and does not require the upstream plugin to be installed.
Slack's repository uses the [MIT license](https://github.com/slackapi/slack-skills-plugin/blob/2c95c4c0fc03a81bb0f15da802ed754dc6d46a8f/LICENSE).
