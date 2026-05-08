# Sandboxed Eval Porting Status

This tracker records CI evals that have been assessed for sandboxed-agent portability.

| CI eval                                    | Status | Sandboxed counterpart                                     | Notes                                                                                                                                                                                             |
| ------------------------------------------ | ------ | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ee/hogai/eval/ci/eval_survey_analysis.py` | Ported | `ee/hogai/eval/sandboxed/surveys/eval_survey_analysis.py` | Portable outcome: retrieve real survey response text via MCP (`execute-sql`) and produce a grounded analysis. The CI-only mocked `SurveyAnalysisTool` call is replaced with seeded survey events. |
