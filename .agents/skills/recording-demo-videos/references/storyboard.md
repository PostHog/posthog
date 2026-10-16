# Storyboard format

A storyboard is one JSON file. Paths in it are relative to the file.

```json
{
  "output": "my-feature-demo.mp4",
  "base_url": "http://localhost:8010",
  "viewport": { "width": 1440, "height": 900 },
  "login": { "email": "test@posthog.com", "password": "12345678" },
  "vars": { "TEAM": "1", "API_KEY": "phs_..." },
  "secrets": ["API_KEY"],
  "hide_text": ["Get more out of PostHog by inviting your team"],
  "hide_selectors": [],
  "title": { "heading": "Feature name", "subheading": "What it does for you.", "hog": "mailbox" },
  "steps": [],
  "end": { "heading": "The change in one line", "subheading": "One supporting line.", "hog": "party" }
}
```

| Key              | Meaning                                                                                                                      |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `output`         | The MP4 path. The sheet, log and error files go next to it. Default `demo.mp4`                                               |
| `base_url`       | The app. Relative step URLs resolve against it. Default `http://localhost:8010`                                              |
| `viewport`       | The video size in pixels. Default 1440×900, which suits Loom and Slack                                                       |
| `login`          | The user the recorder logs in as before recording. Default `test@posthog.com` / `12345678` from `setup_dev`                  |
| `vars`           | Values for `${NAME}` anywhere in the storyboard. Environment variables work too, and `vars` wins                             |
| `secrets`        | Names in `vars` that requests use but the video shows as `$NAME`. Put every API key here                                     |
| `hide_text`      | Hides the smallest container that starts with this text, such as a banner. `DEBUG mode` is always hidden                     |
| `hide_selectors` | CSS selectors to hide. The debug bar (`.tricolor`) is always hidden                                                          |
| `title`, `end`   | Cards before and after the steps: `heading`, `subheading`, `hog` (a slug, see [branding.md](branding.md)) and `hold` seconds |

## Steps

A step runs its keys in this order: `goto`, then `caption`, `scroll`, `hover`, `click`, `type`, then `wait_for`, then `hold`.
A `card` or `http` step does only that.

| Key        | Meaning                                                                                                                                                                           |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `goto`     | A path on `base_url` or a full URL, such as the local inbox at `http://localhost:1080`. The load is cut from the video                                                            |
| `caption`  | Text in the caption bar, kept until the next caption. `""` hides it                                                                                                               |
| `scroll`   | Pixels to scroll down with the mouse wheel (negative scrolls up)                                                                                                                  |
| `hover`    | A target. The cursor glides to it                                                                                                                                                 |
| `click`    | A target. The cursor glides to it and clicks                                                                                                                                      |
| `type`     | `{ "target": …, "keys": ["Home", "ArrowRight x10"], "text": " new words" }`. Clicks the target, presses the keys (`x10` repeats), then types the text                             |
| `wait_for` | A target that must be visible. In a `goto` step it waits after the load, otherwise after the action. The wait is cut from the video, so wait on real content, not on a fixed time |
| `hold`     | Seconds to stay on the result. Default: a third of a second per caption word, at least 2.5                                                                                        |
| `card`     | A full-screen card mid-video, with the same fields as `title`                                                                                                                     |
| `http`     | A terminal card that types out a curl command, sends the request, and shows the response. See below                                                                               |

A step has one `wait_for`. JSON keeps only the last of two equal keys, so a step that needs to wait after a `goto` and again after a `click` must be two steps.

### Targets

| Form                                   | Finds                                                                          |
| -------------------------------------- | ------------------------------------------------------------------------------ |
| `{ "role": "tab", "name": "Metrics" }` | An element by its accessible role and exact name                               |
| `{ "label": "Email" }`                 | A form field by its label                                                      |
| `{ "text": "Password reset" }`         | An element that contains the text. Add `"exact": true` to match the whole text |
| `{ "selector": "[data-attr=save]" }`   | Any Playwright selector, including chains with `>>`                            |

Add `"within": "<css>"` to search inside one element, and `"nth": 1` to take a later match.
Prefer `data-attr` selectors and roles. They survive copy changes.

### HTTP steps

```json
{
  "http": {
    "title": "Send it from your code",
    "method": "POST",
    "url": "/api/projects/${TEAM}/messaging_templates/${TEMPLATE}/send/",
    "headers": { "Authorization": "Bearer ${API_KEY}" },
    "json": { "to": "jane@example.com", "message_data": { "first_name": "Jane" } },
    "expect_status": 202
  }
}
```

The card types out the request as a curl command, with secrets shown as `$NAME`, then sends it and prints the status and the response body.
With `expect_status`, any other status fails the recording, so a broken call never ends up in a finished video.

## Example

This storyboard recorded the transactional email demo. It starts on the template library, makes a template transactional, sends it over the API, shows the email in the local inbox, edits the template, sends again, and ends on the metrics.

```json
{
  "output": "transactional-email-demo.mp4",
  "vars": { "TEAM": "1", "TEMPLATE": "<template id>", "API_KEY": "<project secret API key>" },
  "secrets": ["API_KEY"],
  "hide_text": ["Get more out of PostHog by inviting your team"],
  "title": {
    "heading": "Transactional emails",
    "subheading": "Send any email template from your code, and get workflow reporting for free.",
    "hog": "mailbox"
  },
  "steps": [
    {
      "goto": "/project/${TEAM}/workflows/library",
      "wait_for": { "text": "Password reset" },
      "caption": "Start from an ordinary email template"
    },
    { "click": { "text": "Password reset" }, "wait_for": { "role": "tab", "name": "API" }, "hold": 2 },
    {
      "caption": "The API tab explains what transactional sending does",
      "click": { "role": "tab", "name": "API" },
      "hold": 4
    },
    {
      "caption": "Make transactional creates a hidden workflow with an API trigger",
      "click": { "selector": "[data-attr=make-message-template-transactional]" },
      "wait_for": { "role": "tab", "name": "Metrics" },
      "hold": 2
    },
    {
      "http": {
        "title": "Send it from your code with a project secret API key",
        "url": "/api/projects/${TEAM}/messaging_templates/${TEMPLATE}/send/",
        "headers": { "Authorization": "Bearer ${API_KEY}" },
        "json": { "to": "jane@posthog.com", "message_data": { "first_name": "Jane" } },
        "expect_status": 202
      }
    },
    {
      "goto": "http://localhost:1080",
      "wait_for": { "text": "Reset your password, Jane" },
      "caption": "The email arrives with the data filled in",
      "click": { "text": "Reset your password, Jane" },
      "hold": 5
    },
    {
      "goto": "/project/${TEAM}/workflows/library/templates/${TEMPLATE}",
      "wait_for": { "role": "tab", "name": "Sends" },
      "hold": 0.5
    },
    {
      "caption": "Every send is a workflow run you can inspect",
      "click": { "role": "tab", "name": "Sends" },
      "wait_for": { "text": "SUCCEEDED" },
      "hold": 6
    },
    { "caption": "Edit the template like any other email", "click": { "role": "tab", "name": "Design" }, "hold": 2 },
    {
      "type": {
        "target": { "selector": "text=Subject >> nth=0 >> xpath=following-sibling::*[1]" },
        "keys": ["Control+Home", "Home", "ArrowRight x10"],
        "text": " PostHog"
      },
      "hold": 1
    },
    {
      "caption": "Saving publishes a new version of the workflow",
      "click": { "role": "button", "name": "Save" },
      "hold": 3
    },
    { "click": { "role": "tab", "name": "Versions" }, "hold": 5 },
    {
      "goto": "/project/${TEAM}/workflows/library/templates/${TEMPLATE}",
      "wait_for": { "role": "tab", "name": "Metrics" },
      "hold": 0.5
    },
    {
      "caption": "Sends, deliveries, opens and clicks show up in the metrics",
      "click": { "role": "tab", "name": "Metrics" },
      "wait_for": { "text": "Emails sent" },
      "hold": 7
    }
  ],
  "end": {
    "heading": "Mark it transactional, call one endpoint",
    "subheading": "Everything else runs as a workflow, with metrics, sends and versions.",
    "hog": "party"
  }
}
```
