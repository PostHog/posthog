# Community skills

This directory holds community-contributed PostHog skills — job-to-be-done templates that teach AI agents how to accomplish specific tasks in PostHog.

Skills placed here are distributed alongside official PostHog skills through the agent-skills release pipeline, and surfaced in the skills registry (`skills-index.json`) consumed by the PostHog MCP server, third-party agent frameworks, and IDE extensions.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for the step-by-step contribution workflow, the contract for what a community skill is allowed to contain, and the review checklist.

## Template

A starter skill scaffold lives in [`.template/SKILL.md`](./.template/SKILL.md). The hidden directory prefix keeps it out of the build; copy it to a new directory (named in `lowercase-kebab-case`) when you start a new skill.

## What lives here vs. in `products/<product>/skills/`

| Location                     | Who maintains         | Allowed content                                                                                            |
| ---------------------------- | --------------------- | ---------------------------------------------------------------------------------------------------------- |
| `products/<product>/skills/` | PostHog product teams | Full access: markdown, `references/`, `scripts/`, Jinja2 templates (`.j2`) with access to Pydantic schemas |
| `products/community/skills/` | The community         | Markdown only: `SKILL.md` plus optional `references/*.md`. No `scripts/`, no `.j2` templates               |

The stricter rules for community skills keep the trust boundary clear — community contributions can't execute code, can't introspect Django models, and can't pull in arbitrary runtime context.
