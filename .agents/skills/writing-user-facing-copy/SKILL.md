---
name: writing-user-facing-copy
description: >
  Sets the voice and word choices for any text a person reads in PostHog: UI labels, buttons, tooltips, empty and error states, notifications, in-app messages, onboarding, docs, and support replies.
  Use ALWAYS before writing or editing user-facing copy, and whenever a code change adds or changes a string a user will see.
  Enforces a humane, neutral tone: no editorializing, no sales-y or edgy one-liners, no em-dashes (use hyphens or rewrite), sentence case, plain language.
  Also carries feature-naming rules that are easy to get wrong, most importantly how to talk about the Wizard (name it "Wizard" once, then call it "the setup agent" / "the agent").
  Not for internal code comments, commit messages, or variable names.
---

# Writing user-facing copy

This is the operational gate for anything a person reads in the product or around it.
Run it before writing or editing user-facing text, and whenever a code change introduces or changes a visible string.

Applies to: UI labels, buttons, form fields, tooltips, empty states, error and success messages, toasts and notifications, onboarding flows, emails, docs, and support replies.
Does not apply to: code comments, commit messages, log lines, variable/function names, or other developer-only text.

## Voice

Write the way a person would. Neutral and humane.

- **Sentence case.** Capitalize only the first word and proper nouns. "Save as view", not "Save As View". "Product analytics", not "Product Analytics".
- **Be direct and friendly.** Say what happened and what to do next.
- **Plain language, no jargon.** Use the label the user sees, not the internal name. `surveyPopupDelaySeconds` becomes "Delay the survey popup".
- **Don't editorialize.** State what is, not how exciting it is. Cut "powerful", "seamless", "effortless", "simply", "just", "easily", "supercharge", "unlock".
- **No sales-y or edgy copy.** No marketing hooks, no clever one-liners, no hype.
- **American English spelling.** "color", "analyze", "canceled".

## Specific rules

### No em-dashes

Do not use em-dashes (—) anywhere in user-facing copy.
Do not substitute an en-dash either.

Prefer rewriting the sentence so the dash isn't needed. If a connector is unavoidable, use a hyphen with spaces, a comma, a colon, or split into two sentences.

- ❌ "Save this view — you can reuse it later."
- ✅ "Save this view. You can reuse it later."
- ✅ "Save this view to reuse it later."

Also avoid the sentence *shapes* that lean on that dash, because they read as machine-written:

- ❌ "This isn't just a filter, it's a saved view."  (the "not just X, but Y" construction)
- ❌ "It's fast, it's simple, it's yours."  (rule-of-three padding)
- ❌ Hedging preambles like "It's worth noting that…", "Keep in mind that…".

Write the plain version instead.

### Errors and empty states point to a next step

Say what happened and the next action. Never leave the user staring at a failure with nothing to do.

- ❌ "Something went wrong."
- ✅ "Couldn't load your insights. Refresh the page, and if it keeps happening contact support."

## How to talk about features

Use the names users see, and stay consistent across every surface.

### Wizard

The setup tool is named **Wizard**. It confuses users as a description, because "wizard" reads like an old-style step-by-step form, not an AI. Users already have a mental model for AI agents.

- Use "Wizard" **only** as the feature's proper name (the thing you're pointing at).
- To explain what it does, always call it **"the setup agent"** or **"the agent"**.

Examples:

- ✅ "Wizard sets up PostHog for you. The setup agent installs the SDK and wires up your first events."
- ✅ "Ask the agent to add error tracking."
- ❌ "Use the wizard to walk through setup." (using "wizard" as a description)
- ❌ "The wizard will guide you through each step." (reinforces the wrong mental model)

For any other feature, use its product-facing name exactly as it appears in the UI, and describe it in the terms users already understand.

## When unsure

If you can't tell whether copy reads well, or whether a term is the right user-facing name, ask a human before shipping it.
