---
title: AI platform team structure and collaboration
sidebar: Handbook
showTitle: true
---

This page explains how teams collaborate on AI features at PostHog. For a high-level overview, see the [AI platform overview](/handbook/engineering/ai/ai-platform).

## Who does what

### The PostHog AI team

**The PostHog AI team** is responsible for the architecture, performance, and UX/UI of the AI platform. We review PRs from product teams to ensure they meet our quality bar. We build and maintain the core tooling (`search`, `read_data`, `read_taxonomy`, `enable_mode`). We're also proactive when we see big opportunities for PostHog or when new capabilities can be used across multiple products — things like SQL generation or universal filtering.

### The Array team

**The Array team** is responsible for the Array desktop product, the cloud and local coding agent, and signals and tasks generation. They might at some point own the Wizard or integrate it directly into the main Array product.

### Product teams

**Product teams** add their product-specific tools, modes and features to the platform. They're responsible for:
- Making sure their features are discoverable by users
- Implementing the tool logic for their specific product area
- Adding any necessary frontend components (usually based on the MaxTool frontend class pattern)
- Defining workflows as trajectories for their domain

## How to get started

If you need AI features for your product area, here's the process:

### Step 1: Reach out early

Contact the PostHog AI team lead at #team-posthog-ai in Slack. Tell us what you're thinking, even if it's just a vague idea. We can help you think through whether AI is the right approach and what shape it should take.

### Step 2: Define the use case

Be specific about what AI functionality you need, or work with us to flesh out the requirements. Sometimes what seems like an AI problem is better solved another way, and sometimes what seems like a simple automation turns out to be a perfect AI use case.

### Step 3: Plan the collaboration

We'll figure out the best approach together. This might mean:
- Sending an engineer from the PostHog AI team to your team for a sprint or two
- Building the feature directly in PostHog AI without your team's heavy involvement
- Just giving you enough guidance that you can do it solo

There's no one-size-fits-all model.

### Step 4: Coordinate sprints

Align on timing and resource allocation if needed. This shouldn't feel like a heavyweight process — if it does, we should change it.

## Best practices

### Start small

Begin with simple AI features and iterate based on user feedback. A lot of automation can be broken down into smaller, automatable steps. It's better to ship something that works reliably for one workflow than to build something ambitious that works unreliably for ten workflows.

### Maintain consistency

AI features should follow PostHog's design patterns and UX standards. If you're missing a UX pattern (like a standard way to show AI-generated results, or a loading state for long-running AI tasks), the PostHog AI team can help build reusable components.

## Contact

For questions about working with the AI platform:
- **Slack**: #team-posthog-ai
- **Team page**: [PostHog AI team](/teams/posthog-ai)
- **Objectives**: [Current goals and initiatives](/teams/posthog-ai/objectives)
