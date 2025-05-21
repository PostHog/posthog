from autoevals.partial import ScorerWithPartial
from autoevals.ragas import AnswerSimilarity
from langchain_core.messages import AIMessage as LangchainAIMessage

from braintrust import Score
from posthog.schema import AssistantMessage, AssistantToolCall


class ToolRelevance(ScorerWithPartial):
    semantic_similarity_args: set[str]

    def __init__(self, *, semantic_similarity_args: set[str]):
        self.semantic_similarity_args = semantic_similarity_args

    def _run_eval_sync(self, output, expected, **kwargs):
        if expected is None:
            return Score(name=self._name(), score=1 if not output or not output.tool_calls else 0)
        if output is None:
            return Score(name=self._name(), score=0)
        if not isinstance(expected, AssistantToolCall):
            raise TypeError(f"Eval case expected must be an AssistantToolCall, not {type(expected)}")
        if not isinstance(output, AssistantMessage | LangchainAIMessage):
            raise TypeError(f"Eval case output must be an AssistantMessage, not {type(output)}")
        if output.tool_calls and len(output.tool_calls) > 1:
            raise ValueError("Parallel tool calls not supported by this scorer yet")
        score = 0.0  # 0.0 to 1.0
        if output.tool_calls and len(output.tool_calls) == 1:
            tool_call = output.tool_calls[0]
            # 0.5 point for getting the tool right
            if tool_call.name == expected.name:
                score += 0.5
                if not expected.args:
                    score += 0.5 if not tool_call.args else 0  # If no args expected, only score for lack of args
                else:
                    score_per_arg = 0.5 / len(expected.args)
                    for arg_name, expected_arg_value in expected.args.items():
                        if arg_name in self.semantic_similarity_args:
                            arg_similarity = AnswerSimilarity(model="text-embedding-3-small").eval(
                                output=tool_call.args.get(arg_name), expected=expected_arg_value
                            )
                            score += arg_similarity.score * score_per_arg
                        elif tool_call.args.get(arg_name) == expected_arg_value:
                            score += score_per_arg
        return Score(name=self._name(), score=score)
