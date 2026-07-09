# Agent platform — overview

The 30-second map. One diagram, the whole platform.
For the annotated single-page tour see [full-overview.md](full-overview.md);
for the data model and lifecycle see [architecture.md](architecture.md).

The platform is two halves that share two databases and nothing else:
a **control plane** that authors and promotes agents, and a **data plane**
that runs them.

```mermaid
flowchart TB
    authors["Authors<br/>MCP · console · Claude Code"]
    triggers["Triggers<br/>chat · webhook · Slack · cron · MCP"]

    subgraph control["Control plane — author &amp; promote"]
        django["Django REST"]
        janitor["agent-janitor<br/>bundle CRUD · freeze · validate"]
    end

    subgraph data["Data plane — run"]
        ingress["agent-ingress<br/>auth · route slug → live revision"]
        runner["agent-runner<br/>model loop · tool dispatch"]
    end

    pg[("POSTHOG_DB<br/>applications · revisions<br/>(spec + bundle_uri)")]
    ag[("AGENT_DB<br/>session queue · users · identities")]
    bundles[("Bundle store · S3")]
    memory[("Memory store · S3<br/>per team + app")]

    authors -->|author spec + tools| django
    django <-->|bundle ops| janitor
    django -->|CRUD| pg
    janitor -->|bundle bytes| bundles

    triggers -->|run| ingress
    ingress -->|read live revision| pg
    ingress -->|enqueue session| ag
    ag -->|claim| runner
    runner -->|load revision| pg
    runner -->|fetch bundle| bundles
    runner -->|persist session| ag
    runner -->|memory tools| memory
    runner -. "lifecycle events (Redis)" .-> ingress
    ingress -. SSE .-> triggers
```

The whole flow in one breath:

1. **Author** an agent through Django (spec + tools); the janitor seals its
   bundle into the store and Django records the revision in `POSTHOG_DB`.
2. **Promote** a revision to `live` — the slug now routes to it.
3. A **trigger** hits ingress, which authenticates, resolves the live revision,
   and enqueues a session into `AGENT_DB`.
4. The **runner** claims the session, loads the revision + bundle, runs the
   model loop dispatching tools, and persists the result — streaming lifecycle
   events back to the caller over Redis (SSE).

Read next: [architecture.md](architecture.md) for the data model and revision
lifecycle, then the targeted docs listed in the [README](README.md).
