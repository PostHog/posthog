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
  "voiceover": { "voice": "nPczCjzI2devNBz1zQrb" },
  "music": { "prompt": "Light, upbeat instrumental background music for a product demo." },
  "title": { "heading": "Feature name", "subheading": "What it does for you.", "hog": "mailbox" },
  "steps": [],
  "end": { "heading": "The change in one line", "subheading": "One supporting line.", "hog": "party" }
}
```

| Key              | Meaning                                                                                                                                                                                      |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `output`         | The MP4 path. The sheet, log and error files go next to it. Default `demo.mp4`                                                                                                               |
| `base_url`       | The app. Relative step URLs resolve against it. Default `http://localhost:8010`                                                                                                              |
| `viewport`       | The video size in pixels. Default 1440×900, which suits Loom and Slack                                                                                                                       |
| `login`          | The user the recorder logs in as before recording. Default `test@posthog.com` / `12345678` from `setup_dev`                                                                                  |
| `vars`           | Values for `${NAME}` anywhere in the storyboard. Environment variables work too, and `vars` wins                                                                                             |
| `secrets`        | Names in `vars` that requests use but the video shows as `$NAME`. Names that end in `KEY`, `TOKEN`, `SECRET` or `PASSWORD` are secret without being listed. List every other credential here |
| `hide_text`      | Hides the smallest container that starts with this text, such as a banner. `DEBUG mode` is always hidden                                                                                     |
| `hide_selectors` | CSS selectors to hide. The debug bar (`.tricolor`) is always hidden                                                                                                                          |
| `title`, `end`   | Cards before and after the steps: `heading`, `subheading`, `hog` (a slug, see [branding.md](branding.md)), `say` and `hold` seconds                                                          |
| `voiceover`      | Optional. Narrates the video with ElevenLabs. See [Voiceover](#voiceover)                                                                                                                    |
| `music`          | Optional. A music bed under the video. See [Music](#music)                                                                                                                                   |

## Steps

A step runs its keys in this order: `goto`, then `caption` (and its voiceover line), `scroll`, `hover`, `click`, `type`, then `wait_for`, `sticker`, then `hold`.
A `card` or `http` step does only that.

| Key        | Meaning                                                                                                                                                                                                         |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `goto`     | A path on `base_url` or a full URL, such as the local inbox at `http://localhost:1080`. The load is cut from the video                                                                                          |
| `caption`  | Text in the caption bar, kept until the next caption. `""` hides it                                                                                                                                             |
| `scroll`   | Pixels to scroll down with the mouse wheel (negative scrolls up)                                                                                                                                                |
| `hover`    | A target. The cursor glides to it                                                                                                                                                                               |
| `click`    | A target. The cursor glides to it and clicks                                                                                                                                                                    |
| `type`     | `{ "target": …, "keys": ["Home", "ArrowRight x10"], "text": " new words" }`. Clicks the target, presses the keys (`x10` repeats), then types the text                                                           |
| `wait_for` | A target that must be visible. In a `goto` step it waits after the load, otherwise after the action. The wait is cut from the video, so wait on real content, not on a fixed time                               |
| `say`      | The voiceover line for the step, when it should differ from the caption. `""` keeps the step silent                                                                                                             |
| `sticker`  | A hedgehog that pops in once the action is done: `{ "hog": "mailbox", "text": "You've got mail", "position": "bottom-right", "seconds": 3 }`. Positions: `bottom-right`, `bottom-left`, `top-right`, `top-left` |
| `zoom`     | `true` frames the clicked or typed-in target until just after the action. `{ "target": …, "level": 1.6 }` frames a detail once it is on screen, for the rest of the step. See [Zoom](#zoom)                     |
| `hold`     | Seconds to stay on the result. Default: a quarter of a second per caption word, at least 1.5. With a voiceover, half a second, and the step always waits for its line to finish. Usually leave it unset         |
| `card`     | A full-screen card mid-video, with the same fields as `title`                                                                                                                                                   |
| `http`     | A terminal card that types out a curl command, sends the request, and shows the response. See below                                                                                                             |

A step has one `wait_for`. JSON keeps only the last of two equal keys, so a step that needs to wait after a `goto` and again after a `click` must be two steps.

Use one or two stickers in a video, on the moments that pay off, such as the email arriving. More than that, and they stop meaning anything.

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
The video masks secret values in all the text it shows, including the response body. It also masks PostHog secret keys, such as `phx_` and `phs_` keys.
It cannot mask what a `type` step types into the app or what the app itself shows, so never type a secret in a demo.
With `expect_status`, any other status fails the recording, so a broken call never ends up in a finished video.

## Zoom

A step with `zoom` moves the camera in, and the camera eases back out when the step ends.
Captions, stickers and cards stay put, because they are drawn over the zoomed frame.
A zoom upscales the recorded page, so zoomed text is a little soft. Keep zooms to about 1.5x when text has to be read.

- `"zoom": true` frames what the step clicks or types into, from the moment the pointer heads for it until about half a second after the action. The page usually changes after a click, so the camera does not stay.
- `"zoom": { "target": { "selector": "[data-attr=draft-tag]" }, "level": 1.8 }` frames something the step produced, such as a new tag, a count or a table row, from when it is on screen to the end of the step.

Without `level`, the zoom fills about half the view with the target, between 1.25x and 2x.
Pick two to five beats in a video. The key click and the proof are usually enough.

## Voiceover

`voiceover` narrates the video with ElevenLabs.
Each caption is spoken, unless the step has a `say` line. Cards say their heading and subheading, and HTTP steps their title.
The whole script goes to ElevenLabs as one take, so the delivery flows instead of restarting on each line.
The per-character timestamps cut the take into one clip per line, and each clip starts when its caption shows.

```json
{
  "voiceover": {
    "voice": "nPczCjzI2devNBz1zQrb",
    "model": "eleven_v3",
    "settings": { "stability": 0.5, "speed": 1.12 }
  }
}
```

All three fields are optional. The defaults are Brian, a premade voice, at the settings the DevEx videos use.
Use premade voices only: the account also holds cloned voices of real people.
v3 audio tags such as `[excited]` in a `say` line steer the delivery.

The voiceover needs `ELEVENLABS_API_KEY` in the environment.
Never put the key in a storyboard, a commit, or the chat. Ask the developer to set it in the shell or as a task secret.
Without the key, the recorder records the video with no voiceover and lists `voiceover` under `skipped_without_elevenlabs_key` in the log.
Takes are cached in `~/.cache/posthog-demo-videos/voiceover/` by text and voice, so recording again with the same script costs no credits.
A changed line reads the whole take again. A video is about 1,500 characters, and shared accounts have a monthly limit, so settle the captions before you add the voiceover.

## Music

`music` lays a quiet music bed under the whole video. It fades in and out, and dips while a line or a sticker sound plays.

```json
{ "music": { "prompt": "Light, upbeat instrumental background music for a product demo.", "volume": 0.18 } }
```

- `prompt`: what ElevenLabs Music generates. Optional, with a light, upbeat default. The track is always instrumental.
- `volume`: the bed's level before ducking, from 0 to 1. Default 0.18.
- `file`: a music file to use instead of generating one, relative to the storyboard. Use only music PostHog has the rights to.

Generated tracks match the video's length in 10 second steps, and are cached in `~/.cache/posthog-demo-videos/music/` by prompt and length, so another take of the same length costs nothing.
Music uses the same `ELEVENLABS_API_KEY`, and the key needs music access.
The final mix is normalized to -16 LUFS, the usual level for web video.

## Example

This storyboard records the narrated transactional email demo. It starts on the template library, makes a template transactional, sends it over the API, shows the email in the local inbox, edits the template, sends again, and ends on the metrics.
It sets `hold` only on the two sticker steps and on navigation steps that must stay short.
`TEAM`, `TEMPLATE` and `POSTHOG_PROJECT_SECRET_API_KEY` come from the seed script's env file, see [seeding.md](seeding.md).

```json
{
  "output": "transactional-email-demo.mp4",
  "secrets": ["POSTHOG_PROJECT_SECRET_API_KEY"],
  "hide_text": ["Get more out of PostHog by inviting your team"],
  "voiceover": {},
  "music": {},
  "title": {
    "heading": "Transactional emails",
    "subheading": "Send any email template from your code, and get workflow reporting for free.",
    "hog": "mailbox"
  },
  "steps": [
    {
      "goto": "/project/${TEAM}/workflows/library",
      "wait_for": {
        "text": "Password reset"
      },
      "caption": "Start from an ordinary email template"
    },
    {
      "click": {
        "text": "Password reset"
      },
      "wait_for": {
        "role": "tab",
        "name": "API"
      }
    },
    {
      "caption": "The API tab explains what transactional sending does",
      "click": {
        "role": "tab",
        "name": "API"
      }
    },
    {
      "caption": "Make transactional creates a hidden workflow with an API trigger",
      "click": {
        "selector": "[data-attr=make-message-template-transactional]"
      },
      "wait_for": {
        "role": "tab",
        "name": "Metrics"
      }
    },
    {
      "http": {
        "title": "Send it from your code with a project secret API key",
        "method": "POST",
        "url": "/api/projects/${TEAM}/messaging_templates/${TEMPLATE}/send/",
        "headers": {
          "Authorization": "Bearer ${POSTHOG_PROJECT_SECRET_API_KEY}"
        },
        "json": {
          "to": "jane@posthog.com",
          "identifiers": {
            "distinct_id": "jane"
          },
          "message_data": {
            "first_name": "Jane",
            "reset_link": "https://posthog.com/reset"
          }
        },
        "expect_status": 202
      }
    },
    {
      "goto": "http://localhost:1080",
      "wait_for": {
        "text": "Reset your password, Jane"
      },
      "caption": "The email arrives with message_data filled into the template",
      "click": {
        "text": "Reset your password, Jane"
      },
      "hold": 2,
      "sticker": {
        "hog": "mailbox",
        "text": "You've got mail",
        "seconds": 3
      }
    },
    {
      "goto": "/project/${TEAM}/workflows/library/templates/${TEMPLATE}",
      "wait_for": {
        "role": "tab",
        "name": "Sends"
      },
      "hold": 0.5
    },
    {
      "caption": "Every send is a workflow run you can inspect",
      "click": {
        "role": "tab",
        "name": "Sends"
      },
      "wait_for": {
        "text": "SUCCEEDED"
      }
    },
    {
      "caption": "Edit the template like any other email",
      "click": {
        "role": "tab",
        "name": "Design"
      }
    },
    {
      "type": {
        "target": {
          "selector": "text=Subject >> nth=0 >> xpath=following-sibling::*[1]"
        },
        "keys": ["Control+Home", "Home", "ArrowRight x10"],
        "text": " PostHog"
      }
    },
    {
      "caption": "Saving publishes a new version for the next send",
      "click": {
        "role": "button",
        "name": "Save"
      }
    },
    {
      "click": {
        "role": "tab",
        "name": "Versions"
      },
      "caption": "Every save is a version you can restore"
    },
    {
      "http": {
        "title": "Send again",
        "method": "POST",
        "url": "/api/projects/${TEAM}/messaging_templates/${TEMPLATE}/send/",
        "headers": {
          "Authorization": "Bearer ${POSTHOG_PROJECT_SECRET_API_KEY}"
        },
        "json": {
          "to": "sam@posthog.com",
          "identifiers": {
            "distinct_id": "sam"
          },
          "message_data": {
            "first_name": "Sam",
            "reset_link": "https://posthog.com/reset"
          }
        },
        "expect_status": 202
      }
    },
    {
      "goto": "http://localhost:1080",
      "wait_for": {
        "text": "Reset your PostHog password, Sam"
      },
      "caption": "The next email uses the new subject",
      "click": {
        "text": "Reset your PostHog password, Sam"
      }
    },
    {
      "goto": "/project/${TEAM}/workflows/library/templates/${TEMPLATE}",
      "wait_for": {
        "role": "tab",
        "name": "Metrics"
      },
      "hold": 0.5
    },
    {
      "caption": "Sends, opens and clicks show up in the metrics",
      "click": {
        "role": "tab",
        "name": "Metrics"
      },
      "wait_for": {
        "text": "Emails sent"
      },
      "hold": 2,
      "sticker": {
        "hog": "chart",
        "text": "Tracked",
        "seconds": 3,
        "position": "top-right"
      }
    },
    {
      "goto": "/project/${TEAM}/workflows/library",
      "wait_for": {
        "text": "Password reset"
      },
      "caption": "Transactional templates are tagged, with a filter in the library",
      "click": {
        "selector": "[data-attr=templates-transactional-only]"
      }
    }
  ],
  "end": {
    "heading": "Mark it transactional, call one endpoint",
    "subheading": "Everything else runs as a workflow, with metrics, sends and versions.",
    "hog": "party"
  }
}
```
