---
title: Docs-in-Monorepo Preview (PoC)
sidebar: Engineering
showTitle: true
---

# Hello Team! 👋

**You are viewing a live preview of documentation from the PostHog/posthog monorepo!**

This page lives in the PostHog monorepo at `docs/published/test-preview.md`, not in posthog.com. When you update docs in a PostHog PR, they automatically preview on posthog.com.

## Why This Matters

Engineers can now:

- Write docs alongside code in the same PR
- Preview docs on posthog.com before merging
- Keep docs and code in sync

Website team can:

- Get fresh technical content automatically
- Focus on user-facing docs and design
- Trust that engineering docs stay current

## How It Works

### When You Update Docs in PostHog/posthog

```text
┌─────────────────────────────────────────────────────┐
│ PostHog/posthog (Your PR)                           │
│                                                      │
│  You edit: docs/published/some-doc.md               │
│            ↓                                         │
│  Push to branch: feature/my-feature                 │
│            ↓                                         │
│  GitHub Action detects /docs/** change              │
└────┼────────────────────────────────────────────────┘
     │
     │ Sets POSTHOG_DOCS_REF=feature/my-feature
     │ Triggers posthog.com preview build
     ↓
┌─────────────────────────────────────────────────────┐
│ Vercel (posthog.com preview)                        │
│                                                      │
│  Clones: PostHog/posthog@feature/my-feature         │
│          ↓ (only /docs/ directory)                  │
│  Builds: posthog.com with your docs                 │
│          ↓                                           │
│  Preview URL ready in ~2 minutes ✨                  │
└─────────────────────────────────────────────────────┘

Result: Review code and docs together with live preview!
```

### When You Update posthog.com Content

```text
┌─────────────────────────────────────────────────────┐
│ PostHog/posthog.com (Your PR)                       │
│                                                      │
│  You edit: contents/docs/user-guide.md              │
│            ↓                                         │
│  Push to branch: fix/typo                           │
│            ↓                                         │
│  Vercel auto-deploys preview                        │
└────┼────────────────────────────────────────────────┘
     │
     │ (uses default: POSTHOG_DOCS_REF=master)
     ↓
┌─────────────────────────────────────────────────────┐
│ Vercel (posthog.com preview)                        │
│                                                      │
│  Clones: PostHog/posthog@master                     │
│          ↓ (stable engineering docs)                │
│  Builds: Your changes + latest published docs       │
│          ↓                                           │
│  Preview URL ready ✨                                │
└─────────────────────────────────────────────────────┘

Result: Your posthog.com changes previewed with stable
        monorepo docs from master branch.
```

## What Goes Where

### PostHog Monorepo (`/docs/`)

Technical documentation that changes with code:

- **`/docs/published/`** → Published on posthog.com
  - Architecture guides
  - Engineering practices
  - System design docs
  - Runbooks

- **`/docs/internal/`** → GitHub only (not published)
  - Development workflows
  - Migration patterns
  - Internal processes

### posthog.com (`/contents/`)

User-facing documentation:

- Product tutorials
- User guides
- API reference
- Marketing content

## The Big Picture

```text
┌──────────────────┐         ┌──────────────────┐
│ PostHog/posthog  │         │ posthog.com      │
│                  │         │                  │
│ /docs/published/ │────────▶│ Engineering docs │
│ - Architecture   │  Built  │ + User guides    │
│ - Engineering    │  into   │ + Tutorials      │
│ - Runbooks       │ ────────│ + Marketing      │
│                  │         │                  │
│ Code + Docs      │         │ Complete website │
│ same PR ✅       │         │ merged content ✅ │
└──────────────────┘         └──────────────────┘
```

## Try It Out

This document is in `PostHog/posthog` - when merged to master, it will appear on production posthog.com automatically!

---

**Questions?** Ask in #team-website

## Update: Path Fix Verification

Testing after removing POSTHOG_REPO_PATH and fixing path duplication bug. The clone script now correctly creates `.posthog-monorepo-cache/docs/published/` structure, and gatsby-config always joins `source.path + github.path`.

This update verifies the fix works end-to-end!
