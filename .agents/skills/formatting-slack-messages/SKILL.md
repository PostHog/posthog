---
name: formatting-slack-messages
description: >
  Builds and validates Slack Block Kit messages, modals, and App Home layouts.
  Use for Slack formatting, block selection, Markdown, cards, tables, charts,
  metadata, buttons, and menus. Covers live schemas, payload validation,
  accessibility, and actual Slack rendering. Not for workspace setup.
---

# Formatting Slack messages

Build a layout that makes the result, its context, and the next action clear.
This workflow adapts Slack's official Block Kit skill.
It is self-contained; another installed skill is not required.
See [sources](references/block-selection.md#sources-and-attribution) for upstream attribution.

## 1. Identify the surface and the change

Infer the surface from the request or existing payload:

- A message has `blocks` or `attachments` and goes to a channel or direct message.
- A modal has `type: modal` and a view lifecycle.
- An App Home view has `type: home` and is published for a user.

Inspect the existing payload before changing its layout.
For modifications, preserve unchanged content, source links, `block_id`, `action_id`, values, and menu choices.
Ask only when missing information changes the implementation. Do not repeat questions the user already answered.
For a clear small edit, read the relevant schema, make the edit, and validate it.
For a broad redesign, establish the content order before building the payload.

## 2. Read live schemas

Use the [Block Kit index](https://docs.slack.dev/reference/block-kit) to find the current component pages.
Fetch each selected block, element, and composition object's schema and example.
Append `.md` to Slack documentation URLs when a Markdown response is easier to read.
Follow index links rather than guessing slugs; select menus share one reference page.
Reuse pages already read during the task.

Check required fields, allowed nesting, text types, limits, and supported surfaces separately.
Do not treat this skill's comparison tables as permanent schemas.

Common errors:

- `markdown` is a block type. It is not a text-object type.
- Text objects use `plain_text` or `mrkdwn`. A `text` element is valid inside the appropriate `rich_text` structure, not as a standalone block.
- Valid JSON does not establish valid Block Kit.
- A schema-validation success does not establish surface compatibility or block-count compliance.

## 3. Match the structure to the content

| Content                                                       | Starting point                                             |
| ------------------------------------------------------------- | ---------------------------------------------------------- |
| One change or important number                                | A short sentence with its comparison and units             |
| Independent facts about one item                              | `section.fields` with short labels and values              |
| Several comparable rows                                       | `table`                                                    |
| Rows that need sorting, pagination, filtering, or row actions | `data_table`                                               |
| A compact entity with a short body and a few buttons          | `card`                                                     |
| Optional peer items for browsing                              | A `carousel` of cards                                      |
| A related group of blocks                                     | `container`                                                |
| A real task or investigation step with progress updates       | `task_card` or `plan`                                      |
| A view-wide notice in a modal                                 | `alert`                                                    |
| Existing generated Markdown                                   | `markdown`, if supported and safe for the intended message |
| Formatted text assembled in code                              | `rich_text`                                                |

Use [block selection](references/block-selection.md) for limits, table comparisons, and template patterns.
Keep required findings visible outside carousels, pagination, and collapsed groups.
Do not add dividers between every block or put a one-line notice in a card without a reason.
Use a consistent size and hierarchy across comparable messages.
Keep at most one visually primary action per message or view. Leave equal navigation choices unstyled.

For modals, check the view wrapper, title, callback, close, and submit requirements.
An input-containing modal needs a submit action. Do not compete with Submit using another primary button.
For App Home, handle first use, empty results, and view refresh for the current user.
Use task cards for work with progress updates. Their states describe task progress.

## 4. Establish a clear hierarchy

- Lead with the main result or subject. Link its name to the source when useful.
- Explain the result in a short sentence before optional detail.
- Group related metadata and keep units with values.
- Avoid repeating the same title, link, or value in adjacent blocks unless it answers a different question.
- Keep required information and actions outside collapsed or paginated detail.
- Use consistent widths and emphasis for comparable items.
- State status in words. Do not rely on color or emoji alone.
- Show only facts the source provides. Do not invent priority, causes, or recommendations.

Use inline code for identifiers, literal values, names, or short phrases when that emphasis helps the reader.
Keep surrounding text regular. Reserve stronger emphasis for the few items that matter most.
Follow the user's chosen emphasis style; do not bold every label and value.
Use descriptive action labels and avoid duplicate navigation controls.
For a one-time notification, use wording that remains accurate later. A current status needs an update lifecycle.

### Text formats and safe content

- `mrkdwn` uses `*bold*`, `_italic_`, backticks, and `<url|label>` links.
- A native `markdown` block uses standard Markdown, including `**bold**` and `[label](url)` links.
- `rich_text` uses typed elements and explicit styles. Use its `code` style for inline-code emphasis.

Do not pass one format into another unchanged.
Keep dynamic text separate from formatting syntax. Apply the required link policy before adding links.
Escape dynamic `mrkdwn` values and prevent unintended mentions. Keep literal identifiers separate from formatting.
Use Unicode emojis or supported emoji elements; check the text object's `emoji` behavior.

### Charts and accessibility

Choose an image block for a supplied chart image. Use a native chart block when its supported features fit the data.
State the main finding in text and provide useful `alt_text` for images.
Check labels, units, image size, and readability on narrow screens.

Supply useful notification and screen-reader fallback text.
Do not clear top-level `text` only to remove duplication; adjust the visible heading and check the result.
An attachment fallback is not proof of equivalent accessibility or notification behavior.
Button labels must explain their action without relying on color or an icon.

## 5. Validate the payload

Use [blocks.validate](https://docs.slack.dev/reference/methods/blocks.validate/) with concrete values in place of placeholders.
Read the live method reference before choosing request parameters.
Send exactly one of:

- `blocks`: the JSON-encoded block array.
- `message`: the JSON-encoded complete message, including attachments.
- `view`: the JSON-encoded modal or App Home view.

The method requires no scopes. Use an available Slack API client or connector.
If a Slack CLI is available, read its help before using its API or authentication flags.
Do not hardcode CLI flags from memory.

Inspect `ok` and each validation error's pointer, message, and constraint.
Fix the offending fields and validate again.
Check supported surfaces and count limits independently, including nested blocks.
For example, `alert` is modal-only, and a container accepts at most ten child blocks.
A validation success is a schema result, not a visual or functional approval.

## 6. Inspect the rendered layout

Use Block Kit Builder to inspect the intended surface with representative sample content.
If the user authorizes a live message, send the payload to the authorized destination and inspect its rendering.

Check:

- Long text, long names, missing fields, and empty results.
- Desktop and narrow layouts.
- Initial expansion, pagination, and content hidden by scrolling.
- Text hierarchy, links, emojis, and image readability.
- Notification and screen-reader fallback text.
- Button labels and placement. Check interaction behavior separately when it is in scope.

Legacy colored attachments can collapse. Check block support before nesting newer components inside them.
Keep essential content visible in the initial layout.
Compare layouts with the same content so their differences are clear.
Distinguish schema validation, visual inspection, and interaction checks when reporting results.
