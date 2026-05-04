# Sandboxed Eval Porting Status

Sandboxed ports should measure portable outcomes: MCP tool calls, created or updated entities, query payloads, final messages, and other artifacts an arbitrary agent can produce against the live test world.

Harness-specific CI assertions such as Max graph routing, `AssistantState` shape, `AssistantNodeName` transitions, LangGraph internals, slash commands, Max memory, and persona behavior should not be ported one-for-one.

| CI eval                                                     | Status | Sandbox counterpart                                                  | Notes                                                                                                                                                          |
| ----------------------------------------------------------- | ------ | -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ee/hogai/eval/ci/max_tools/eval_create_experiment_tool.py` | Ported | `ee/hogai/eval/sandboxed/experiments/eval_create_experiment_tool.py` | Portable. Scores successful `experiment-create` MCP output, requested variant configuration, draft status, and the created experiment ID in the final message. |
