# `hog setup`

`run.ts` runs the steps in order. Each step has its own file under `steps/`, numbered in that order.
A step is either done, does its work, or stops with the next action: what you or the agent do before the next `hog setup next`.
`hog setup` only describes the current step, and `hog setup next` keeps going until a step stops.

The rule for every step: an option counts as an answer as soon as it is given, and a prompt at a terminal asks only for the answers the options left out.
The install step has no option, so it ends only on a `hog setup next` that started on it, which means the agent always reads its instructions first.

| File                   | Holds                                                                                         |
| ---------------------- | --------------------------------------------------------------------------------------------- |
| `run.ts`               | The step order, the loop, and the summary of a connected folder                               |
| `setup-run.ts`         | `SetupRun`, what one call knows: the folder, its login, the products                          |
| `result.ts`            | The result types, which the agent reads as JSON                                               |
| `state.ts`             | The state file each folder keeps in `~/.posthog/setup/`                                       |
| `products.ts`          | The product table that `--products` picks from                                                |
| `agents-md.ts`         | The PostHog section in `AGENTS.md` and `CLAUDE.md`                                            |
| `steps/<nn>-<step>.ts` | One step each, in the order of `STEP_IDS` in `state.ts`: `01-purpose.ts` to `10-connected.ts` |

The diagrams show who talks to whom in each step. The numbers match the files in `steps/`.

## You at a terminal

You run every command, and `hog` asks its questions as prompts.

```mermaid
sequenceDiagram
    actor You
    participant hog as hog CLI
    participant PH as PostHog

    Note over You,PH: 1. purpose
    You->>hog: hog setup next
    hog->>You: What do you want to use PostHog for? Which products? Which region?
    You->>hog: Your answers

    Note over You,PH: 2. login
    hog->>PH: Start a device login
    hog->>You: Open the browser with a code
    You->>PH: Log in or sign up, then approve
    PH-->>hog: Token for one project

    Note over You,PH: 3. project, 4. agents-md
    hog->>PH: Record the products you picked
    hog->>hog: Write posthog.json and the PostHog section in AGENTS.md

    Note over You,PH: 5. install
    hog->>You: Read the install skill with two hog learn commands
    You->>hog: hog learn posthog:instrument-integration (and its COMMANDMENTS.md)
    You->>You: Install PostHog in the app
    You->>hog: hog setup next

    Note over You,PH: 6. review
    hog->>You: Do your changes follow every install rule?
    You->>hog: Yes

    Note over You,PH: 7. verify
    hog->>PH: Any events since setup started? (for up to 30 seconds)
    PH-->>hog: The event count, or none yet

    Note over You,PH: 8. products, 9. mcp, 10. connected
    hog->>hog: Check whether your agent has PostHog's MCP server
    hog->>hog: Write the final PostHog section in AGENTS.md
    hog->>You: The event count, what else PostHog can do, the skills you can add, and hog mcp add
```

## You with a coding agent

The agent runs every command. It asks you what PostHog is for only when it can't tell, you approve the login, and it tells you what else PostHog can do at the end of its turn.

```mermaid
sequenceDiagram
    actor You
    participant Agent
    participant hog as hog CLI
    participant PH as PostHog

    Note over You,PH: 1. purpose
    Agent->>hog: hog setup next
    hog-->>Agent: ask_user, with the question and the product list
    opt The agent can't tell what PostHog is for
        Agent->>You: What do you want to use PostHog for?
        You->>Agent: Your answer
    end
    Agent->>hog: hog setup next --reason "..." --products a,b

    Note over You,PH: 2. login
    hog->>PH: Start a device login
    hog-->>Agent: wait, with a link and a code
    Agent->>You: Open the link, check the code, approve
    Agent->>hog: hog setup next (waits for the approval)
    You->>PH: Log in or sign up, then approve
    PH-->>hog: Token for one project

    Note over You,PH: 3. project, 4. agents-md
    hog->>PH: Record the products you picked
    hog->>hog: Write posthog.json and the PostHog section in AGENTS.md

    Note over You,PH: 5. install
    hog-->>Agent: read, with two hog learn commands
    Agent->>hog: hog learn posthog:instrument-integration (and its COMMANDMENTS.md)
    Agent->>Agent: Install PostHog in the app
    Agent->>hog: hog setup next

    Note over You,PH: 6. review
    hog-->>Agent: read, to check the changes against the install rules
    Agent->>Agent: Fix any change that breaks a rule
    Agent->>hog: hog setup next --reviewed

    Note over You,PH: 7. verify
    hog->>PH: Any events since setup started? (for up to 30 seconds)
    PH-->>hog: The event count, or none yet

    Note over You,PH: 8. products, 9. mcp, 10. connected
    hog->>hog: Check whether the agent has PostHog's MCP server
    hog->>hog: Write the final PostHog section in AGENTS.md
    hog-->>Agent: done, with the event count, the products, the skills and the MCP check
    Agent->>You: At the end of its turn: what else PostHog can do, hog skills add, and hog mcp add when the server is missing
```
