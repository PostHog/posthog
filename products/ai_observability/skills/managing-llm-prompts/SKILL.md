---
name: managing-llm-prompts
description: >
  Create, version, release, and wire up LLM prompts with PostHog prompt management.
  Use when a user asks to create or edit a prompt in PostHog, move hardcoded prompts
  out of their code, change a prompt without a deploy, release or roll back a prompt
  version with a label such as production, or fetch prompts at runtime with the
  Python or Node SDK. Covers the order of the llma-prompt tools, safe edits of
  existing prompts, labels as the release step, the fetch code with a fallback,
  and how to confirm that the application really fetches the prompt.
---

# Managing LLM prompts

Prompt management stores prompts in PostHog as immutable versions.
The application fetches a prompt at runtime, so a prompt change needs no deploy.

A prompt that exists in PostHog but that no code fetches changes nothing for the user.
The job is complete only when the application fetches the prompt, or when the user has said they will connect it themselves.
If you only create the prompt, say plainly that the application does not use it yet and offer to connect it.

Read [the prompt management docs](https://posthog.com/docs/prompt-management) for SDK options, caching behavior, and limits.
This skill covers the order of work and the checks.

## Start from what the user has

- **Prompts hardcoded in the code.** Find the prompt strings the application sends to a model.
  Move the ones the user names. If the user names none, list what you found and ask which to move.
- **A new prompt.** Create it, then connect the code that will use it.
- **A prompt that already exists in PostHog.** Go to [Change an existing prompt](#change-an-existing-prompt).

Call `posthog:llma-prompt-list` first in every case.
A prompt with the same purpose may already exist, and names must be unique.

## Create the prompt

Use `posthog:llma-prompt-create`.

- A name allows letters, numbers, hyphens, and underscores. The name `new` is reserved.
  A name cannot change after creation, and the code refers to the prompt by it.
  Choose a name that describes the job, for example `support-reply-system`.
- Write runtime values as `{{variable}}`.
  When you move a prompt out of code, convert each f-string field or template literal placeholder to this form and keep the variable names.
  `compile` only substitutes values. A format spec such as `{amount:.2f}` or an expression such as `${items.length}` stays in the application code, which passes the result as a plain variable.
- Put model settings (model, temperature, tool definitions) in `config` when the user wants to change them without a deploy.
  `config` is versioned with the prompt.
- Copy the prompt text exactly when you move it. Do not improve the wording in the same step.
  The first version must behave the same as the hardcoded one.

## Release with a label

Publishing a version and releasing it are separate steps.
A label is a pointer to one version. Code that fetches by label gets a new version only when the label moves.

1. After you create the prompt, call `posthog:llma-prompt-label-set` to point `production` at version 1.
2. Make the code fetch with `label='production'`.
3. Later versions stay out of production until someone moves the label.

Code that fetches without a label or version gets the latest version, so every publish is live within the cache time.
Use that only when the user asks for it.

Do not move a label that running code already fetches unless the user asked for that release.
Moving `production` changes what the application sends to the model.
To roll back, point the label at the earlier version.

## Change an existing prompt

1. Call `posthog:llma-prompt-get` with `resolve=false`.
   The default response replaces `@@@prompt:...@@@` references with the referenced content. If you publish that text, the references are lost.
2. Call `posthog:llma-prompt-update` with `base_version` set to the version you read, and a `version_description` that says what changed and why.
   A 409 response means someone else published in between. Read the prompt again and apply your change to the new text.
3. Tell the user the new version number and which label, if any, points at it. Ask before you move a label.

## Connect the code

The SDK helper exists for Python (`posthog`) and Node (`@posthog/ai` with `posthog-node`).
For another language, read the docs for current support before you write an HTTP client by hand.

```python
import os

from posthog import Posthog
from posthog.ai.prompts import Prompts

posthog = Posthog(PROJECT_TOKEN, host="https://us.posthog.com", secret_key=os.environ["POSTHOG_PERSONAL_API_KEY"])
prompts = Prompts(posthog)

result = prompts.get("support-reply-system", label="production", with_metadata=True, fallback=ORIGINAL_PROMPT)
system_prompt = prompts.compile(result.prompt, {"company": company})
```

```typescript
import { Prompts } from '@posthog/ai'
import { PostHog } from 'posthog-node'

const posthog = new PostHog(PROJECT_TOKEN, {
  host: 'https://us.posthog.com',
  personalApiKey: process.env.POSTHOG_PERSONAL_API_KEY,
})
const prompts = new Prompts({ posthog })

const result = await prompts.get('support-reply-system', { label: 'production', fallback: ORIGINAL_PROMPT })
const systemPrompt = prompts.compile(result.prompt, { company })
```

Rules that are easy to get wrong:

- **The fetch needs a personal API key with the `llm_prompt:read` scope.** The project token alone is not enough.
  You cannot create this key. Ask the user to create it and to set it as an environment variable or secret. Never write a key into the code.
- **Use the app host**, `https://us.posthog.com` or `https://eu.posthog.com`.
  An ingestion host such as `https://us.i.posthog.com` does not serve prompts.
  `Prompts` takes its host from the PostHog client you pass in.
  If the existing client captures events through an ingestion host, construct `Prompts` directly with the personal API key, the project token, and the app host instead.
- **Keep the original prompt text in the code as the `fallback`.**
  The SDK returns it when PostHog cannot be reached and nothing is cached, so the application keeps working.
- **Create one `Prompts` client for the process**, at module level. Each client has its own cache. A client created per request fetches on every request.
- **Link fetches to traces.** If the application sends LLM events to PostHog, pass `$ai_prompt_name` and `$ai_prompt_version` (from `result.name` and `result.version`) as PostHog properties on the model call.
  The prompt page then shows the traces of each version.
- An application that uses many prompts can load them all in one request at startup. Read "Fetching all prompts in one request" in the docs.

## Confirm the fetch works

A wrong key or host does not raise an error when a fallback is set. The SDK logs a warning, returns the fallback, and the application looks healthy.
Check before you report success.

1. Run the code path once, if you can run the application or its tests against the real API.
2. Read `result.source`. `api` or `cache` means the prompt came from PostHog. `code_fallback` means the fetch failed.
3. Confirm from the PostHog side with `posthog:execute-sql`:

   ```sql
   SELECT timestamp, properties.prompt_version, properties.prompt_label
   FROM events
   WHERE event = '$llm_prompt_fetched'
     AND properties.prompt_name = 'support-reply-system'
     AND timestamp > now() - INTERVAL 1 HOUR
   ORDER BY timestamp DESC
   LIMIT 10
   ```

   Your own `posthog:llma-prompt-get` calls also produce this event.
   Count only an event with a timestamp after the application ran, and do not call `posthog:llma-prompt-get` between the run and this query.
   A bulk fetch produces one event per request with `prompt_count` and no `prompt_name`, so filter on `properties.prompt_fetch_path = 'list'` for that case.

If you cannot run the application, say that the fetch is not verified, and give the user this query to run after their next deploy.

## Report to the user

- The prompt name, the version, and which label points at it.
- The environment variable they must set, and that the key needs the `llm_prompt:read` scope.
- Whether the fetch is verified, and how you checked.
- How to change the prompt from now on: publish a new version in PostHog, then move the `production` label to release it.
