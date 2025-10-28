---
title: Implementing AI features
sidebar: Handbook
showTitle: true
---

This page provides implementation guidance, pricing philosophy, and future directions for the PostHog AI platform. For a high-level overview, see the [AI platform overview](/handbook/engineering/ai/ai-platform).

## Pricing and product positioning

### How we think about pricing

With our AI pricing, we want to follow the [PostHog pricing principles](/handbook/engineering/feature-pricing). Concretely, this means:

1. We offer a generous free tier
2. We charge usage-based instead of a flat subscription

The unit that matches usage the closest is token consumption. This means to fix a SQL query with AI, the user would pay very little, analysing hundreds of session recordings will cost more. Since token costs differ based on token type & model, we are passing on our own costs to our users, with a small markup, instead of having a fixed price per token.

To keep our AI pricing simple, this pricing applies to all AI features once they are in general availability, that means per-product AI features as well as Session summaries and Deep research.

So that users can learn how to use PostHog without worrying about being charged, we are keeping chats that refer to our documentation free without a limit.

### How users should think about our products

**PostHog AI** is the main PostHog product for AI interactions. It's where most users will spend their time. You can switch between Core, Deep research, and Session summaries features depending on what you're trying to do. The UX is better than external tools because we can support sharing, navigation, and linking between AI results and PostHog artifacts. PostHog AI is also trained on PostHog-specific patterns and your actual usage data, so it provides higher quality, more contextual results than a general-purpose AI.

**Deep research** is a feature available within PostHog AI, but also accessible through its own dedicated UI if you want to jump straight into research mode. Use it for open-ended investigative work where you're trying to understand a complex problem.

**Session summaries** is callable from PostHog AI and Deep research, and also has its own UI. Use it when you need to analyze many session recordings and extract patterns or issues.

**Array** is a desktop product for single-engineer use. It's separate from PostHog AI because the workflow is different — you're not asking questions, you're letting an AI agent watch PostHog for problems and automatically fix them in your codebase. Think of it as an AI assistant that lives in your development environment.

**MCP** is for users who prefer to work in third-party tools like Claude Code or VS Code. You get access to PostHog's data and can combine it with other MCP servers (like Hubspot or Zendesk). The trade-off is you don't get PostHog AI's polished UX or PostHog-specific training.

## Implementation recommendations

### For engineers adding AI features

If your feature **reads or writes PostHog data**, build it into PostHog AI or have it hand off to PostHog AI after initiation. For example, if you're adding a "Fix with AI" button to debug SQL queries, that button should open PostHog AI with context about the query, so users can iteratively debug with AI assistance.

If your feature **triggers code changes**, feed it as a signal into the Array product. You can also offer a "copy prompt" option for engineers who don't want to use Array — they can paste the AI-generated prompt into their own code editor.

If your feature **doesn't fit either category**, use your judgment and consult with the PostHog AI team if you're unsure. We're still figuring out where some things fit.

## Future directions

### Third-party context integration

We want to connect PostHog AI to third-party tools for additional context. Imagine PostHog AI analyzing data across PostHog, Slack messages, and Zendesk tickets to understand not just what users are doing, but what they're saying and reporting. This data could also generate signals for the Array product — if users are complaining about a bug in Slack and PostHog sees errors in the same area, that's a strong signal for Array to investigate and potentially fix it automatically.

This is in the idea stage right now, but the PostHog AI team will likely start working on it soon.

### Continuous instrumentation

The Wizard's future evolution involves continuous instrumentation — watching your codebase and suggesting event tracking for new features, filling gaps in existing tracking, and standardizing event patterns. This could integrate with Array to automatically handle PostHog instrumentation when generating code.

### Mode and features expansion

As product teams identify needs, we'll continue adding specialized agent modes and user-facing features. The mode architecture is designed to scale — teams can create their own modes without touching the core agent infrastructure.

### Research improvements

Deep research is being refined with better research strategies, improved denoising algorithms, and more sophisticated pattern recognition. The goal is to reduce rabbit holes and improve data interpretation accuracy.

## Contact and resources

For questions about working with PostHog AI, ask in the #team-posthog-ai Slack channel.

Additional resources:
- [PostHog AI team page](/teams/posthog-ai)
- [PostHog AI user documentation](/docs/posthog-ai)
- [PostHog AI objectives](/teams/posthog-ai/objectives)
- [AI platform overview](/handbook/engineering/ai/ai-platform)
- [Products documentation](/handbook/engineering/ai/products)
- [Architecture documentation](/handbook/engineering/ai/architecture)
- [Team structure documentation](/handbook/engineering/ai/team-structure)
