# `hog setup`

`run.ts` runs the steps in order, and each step lives in its own file under `steps/`.
A step is done, does its work, or stops with the next action: what the person or the agent does before the next `hog setup next`.
`hog setup` only describes the current step, and `hog setup next` keeps going until a step stops.

The rule for every step: an option counts as an answer as soon as it is given, and a prompt at a terminal asks only for the answers the options left out.
The install step has no option, so it ends only on a `hog setup next` that started on it, which means the agent always reads its instructions first.

| File              | Holds                                                                     |
| ----------------- | ------------------------------------------------------------------------- |
| `run.ts`          | The step order, the loop, and the summary of a connected folder           |
| `setup-run.ts`    | `SetupRun`, what one call knows: the folder, its login, the products      |
| `result.ts`       | The result types, which the agent reads as JSON                           |
| `state.ts`        | The state file each folder keeps in `~/.posthog/setup/`                   |
| `products.ts`     | The product table that `--products` picks from                            |
| `agents-md.ts`    | The note in `AGENTS.md` and `CLAUDE.md`                                   |
| `steps/<step>.ts` | One step each: `purpose`, `login`, `project`, `agents-md`, `install`, ... |

In the diagrams, blue is the CLI doing a step on its own, red is the CLI stopping with the next action, yellow is the person, and gray is the agent.

## A person at a terminal

```mermaid
flowchart TD
    classDef phBlue fill:#1d4aff,stroke:#1d4aff,color:#fff;
    classDef phRed fill:#f54e00,stroke:#f54e00,color:#fff;
    classDef phYellow fill:#f9bd2b,stroke:#f9bd2b,color:#000;
    classDef phGray fill:#e5e7eb,stroke:#c7ccd1,color:#000;

    start[Person runs hog setup next]:::phYellow --> purpose{{purpose}}:::phBlue
    purpose -->|prompts| answers[Person answers: what PostHog is for, which products,<br/>and the region when nothing names a host]:::phYellow
    answers --> login{{login}}:::phBlue
    login -->|opens the browser and waits| approve[Person approves the login,<br/>and signs up when new]:::phYellow
    approve --> project[project: writes posthog.json,<br/>records the product intents]:::phBlue
    project --> agentsMd[agents-md: adds the in-progress note]:::phBlue
    agentsMd --> install{{install}}:::phBlue
    install -->|skill files not read| readSkill[Stops: run both hog learn commands]:::phRed
    readSkill --> installs[Person reads the skill, installs PostHog,<br/>and runs hog setup next]:::phYellow
    installs --> install
    install -->|both read| review{{review}}:::phBlue
    review -->|prompts| checked[Person says whether the changes<br/>follow every install rule]:::phYellow
    checked -->|no| readRules[Stops: read the rules again]:::phRed
    readRules --> fixes[Person fixes the changes,<br/>and runs hog setup next]:::phYellow
    fixes --> review
    checked -->|yes| verify{{verify}}:::phBlue
    verify -->|no events, exit code 1| noEvents[Stops: use the app]:::phRed
    noEvents --> uses[Person uses the app,<br/>and runs hog setup next]:::phYellow
    uses --> verify
    verify -->|events arrived| products[products: shows the other products<br/>and the skills to add later]:::phBlue
    products --> connected([connected: final note in AGENTS.md]):::phBlue
```

## A person with an agent

The agent runs every command. The person answers one question, approves the login, and hears what else PostHog can do.

```mermaid
flowchart TD
    classDef phBlue fill:#1d4aff,stroke:#1d4aff,color:#fff;
    classDef phRed fill:#f54e00,stroke:#f54e00,color:#fff;
    classDef phYellow fill:#f9bd2b,stroke:#f9bd2b,color:#000;
    classDef phGray fill:#e5e7eb,stroke:#c7ccd1,color:#000;

    start[Agent runs hog setup next]:::phGray --> purpose{{purpose}}:::phBlue
    purpose -->|no answers| askUser[Stops: ask_user]:::phRed
    askUser --> asks[Agent asks: What do you want to use PostHog for?]:::phGray
    asks --> answers[Person answers]:::phYellow
    answers --> passes[Agent picks the product ids, and runs hog setup next<br/>with the answer as reason and the ids as products.<br/>It adds region eu only for the EU or data residency]:::phGray
    passes --> purpose
    purpose -->|answers given| login{{login}}:::phBlue
    login -->|no approval yet| wait[Stops: wait, with the link and the code]:::phRed
    wait --> handsOver[Agent hands the link and the code to the person,<br/>then runs hog setup next, which waits]:::phGray
    handsOver --> approve[Person approves the login,<br/>and signs up when new]:::phYellow
    approve -->|the waiting hog setup next returns| login
    login -->|approved| project[project: writes posthog.json,<br/>records the product intents]:::phBlue
    project --> agentsMd[agents-md: adds the in-progress note]:::phBlue
    agentsMd --> install{{install}}:::phBlue
    install -->|skill files not read| readSkill[Stops: read, with both hog learn commands]:::phRed
    readSkill --> installs[Agent reads the skill, installs PostHog,<br/>and runs hog setup next]:::phGray
    installs --> install
    install -->|both read, and this call started here| review{{review}}:::phBlue
    review -->|no reviewed option| readRules[Stops: read, with the install rules]:::phRed
    readRules --> checks[Agent checks its changes against each rule,<br/>and runs hog setup next with reviewed]:::phGray
    checks --> review
    review -->|reviewed| verify{{verify}}:::phBlue
    verify -->|no events, exit code 1| noEvents[Stops: run]:::phRed
    noEvents --> uses[Agent runs the app or asks the person to,<br/>then runs hog setup next]:::phGray
    uses --> verify
    verify -->|events arrived| products{{products}}:::phBlue
    products -->|no products-ack option| tellUser[Stops: tell_user]:::phRed
    tellUser --> tells[Agent tells the person what else PostHog can do<br/>and which skills could help later]:::phGray
    tells --> hears[Person hears the options]:::phYellow
    hears --> acks[Agent runs hog setup next with products-ack]:::phGray
    acks --> products
    products -->|products-ack| connected([connected: final note in AGENTS.md]):::phBlue
```
