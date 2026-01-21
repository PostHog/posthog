---
name: implementing-agent-modes
description: Guidelines to create/update a new mode for PostHog AI agent. Modes are a way to limit what tools, prompts, and prompt injections are applied and under what conditions. Achieve better results using your plan mode.
---

# Agent modes

Use the steps below to plan or implement a new mode. A mode is a way to manage the context of the agent and inject tools, prompts, and mode-related behavior relevant to a product, use case, JTBD, etc. The agent has the `switch_mode` tool that allows it to switch itself to another mode, which might change tools, prompt, and executables, preserving the current context. Some previously created tools are contextual, meaning they're injected on particular pages of the frontend. The modes change the approach and always have tools in the mode context.

## Determine mode name

Explore the `ee/hogai/core/agent_modes/presets` directory and check if there are already modes that match the user's intent. If you want to create a new mode, you should scope it by a PostHog product (Product analytics), product area (SQL), or agent (Instrumentation agent).

## (optionally) Create a new mode in schema

Add a new AgentMode to `frontend/src/queries/schema/schema-assistant-messages.ts` and regenerate the schema using:

```bash
hogli build:schema
```

Alternatively, you may use this command:

```bash
pnpm run schema:build
```

## Create or update mode's scaffolding

A mode should typically contain at least two things:

- An AgentToolkit exposing tools that are specific to the mode and trajectory examples for the todo tool.
- An AgentModeDefinition containing the AgentMode, mode description that is always injected into the context window of the agent, and classes for toolkit and executables.

Note: you should only create new executables if the user needs to modify the prompt, behavior of that mode, or the execution loop itself.

## Adding tools to the mode

Relevant tools might be located in `ee/hogai/tools` or `products/<product_name>/backend/max_tools`. There is a set of tools that is always injected into the context, like the `read_data` tool, but all other tools should be specific to the mode.

Before adding a tool to the toolkit, determine if those tools have tool dependencies. If there are dependencies (like an experiment depends on feature flag creation), loop back to the user to determine whether they want to merge modes into a single one. If they don't want to do that, make sure that you later add a trajectory example clearly explaining mode switching and tool selection.

You should also verify that the tools are backend-first. If tools apply frontend changes without passing proper context back to the conversation, you should propose a way to make them backend-first so the agent has the right context.

## Review the default toolkit

If the new mode contains new Django models, you should review whether the `read_data`, `search`, and `list_data` tools have the functionality to retrieve the models. If they don't support these models, you should use or implement one of the context providers available in `ee/hogai/context/...`.

## Write JTBD-like trajectory examples

Update the AgentToolkit to include trajectory examples. These should be JTBD-style examples showing how the agent should achieve typical tasks with the available tools. Check the Product analytics preset for reference.

## Implement frontend

Update `max-constants.tsx` to include new tools and add the mode to the mode selector. You might also need to create new UI elements for displaying data from the tools.

### Example

Say you've updated the Error tracking tool to list issues. It used to be a frontend tool that only updated filters, but now it outputs error tracking issues. While the agent has the context it needs, the user also needs to see the issues in a human-readable way. In this case, you should design and implement a new component to display the tool's output.

## Add feature flag

All new modes must be feature-flagged. Example:

```ee/hogai/chat_agent/mode_manager.py
    @property
    def mode_registry(self) -> dict[AgentMode, AgentModeDefinition]:
        registry = dict(DEFAULT_CHAT_AGENT_MODE_REGISTRY)
        if has_error_tracking_mode_feature_flag(self._team, self._user):
            registry[AgentMode.ERROR_TRACKING] = error_tracking_agent
        return registry
```

If you have created new tools, make sure you feature flag them correctly:

1. Old tools that are being migrated should not be available if the feature flag is active.
2. New tools should only be available if the feature flag is active.

## Implement and update tests

You should test new tools, presets, executables, and optionally implement evals.
