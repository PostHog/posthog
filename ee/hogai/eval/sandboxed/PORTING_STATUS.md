# Sandboxed Eval Porting Status

This tracker was not present in this checkout when the feature flag port was added. Keep rows at CI-eval file granularity.

| CI eval                                                       | Status | Sandboxed counterpart                                               | Notes                                                                                                                                                                            |
| ------------------------------------------------------------- | ------ | ------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ee/hogai/eval/ci/max_tools/eval_create_feature_flag_tool.py` | Ported | `ee/hogai/eval/sandboxed/feature_flags/eval_create_feature_flag.py` | Portable. The sandboxed port asserts on the successful `create-feature-flag` MCP call, the created feature flag configuration, and the created ID returned in the final message. |
