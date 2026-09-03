---
name: organizing-conversations-code
description: >
  File layout for the conversations product. Use when adding, moving, renaming, or reviewing
  files under products/conversations/ — especially frontend components, scenes, helpers, and
  tests. Conversations React components live in their own folder under
  products/conversations/frontend/components/, never as loose files in components/ or at the
  frontend root. Expand this skill as more conversations layout rules land.
---

# Organizing conversations code

Conversations-specific layout. Repo-wide UI rules still apply — read
[writing-ui-components](../../../../.agents/skills/writing-ui-components/SKILL.md) for
one-component-per-file, no barrels, and import sweeps. This skill owns _where in
conversations_ a file goes.

## Use this skill when

- Creating, moving, or renaming a file under `products/conversations/`
- Adding a React component, helper, or test to conversations frontend
- Reviewing a conversations diff that adds files

## Components

Every React component lives in its own folder under `products/conversations/frontend/components/`.
The file is named after the export.

```text
products/conversations/frontend/components/<Name>/<Name>.tsx
products/conversations/frontend/components/<Name>/<Name>.test.tsx   # colocated
```

Import the file, not the folder:

```ts
import { SlaDisplay } from '../../components/SlaDisplay/SlaDisplay'
import { SlaDisplay } from 'products/conversations/frontend/components/SlaDisplay/SlaDisplay'
```

Do not:

- Drop a component as a loose file in `frontend/components/`
- Put a component at `products/conversations/frontend/` (the product frontend root)
- Add an `index.ts` barrel so callers can import the folder

A helper that returns props or data — not markup — is not a component. Keep it next to the
feature or at `products/conversations/frontend/<name>.ts(x)` (see `clearFilterButtonProps.tsx`).

When you move a component, `git mv`, point every consumer at the new path, and delete the old
one. No re-export shim.
