import { formatTokens } from "./spendAnalysisFormat";
import type { SpendAnalysisResponse } from "./spendAnalysisTypes";

export function deriveSpendSuggestions(data: SpendAnalysisResponse): string[] {
  const suggestions: string[] = [];
  const { summary } = data;
  const toolItems = data.by_tool.items;

  if (summary.total_cost_usd === 0) {
    return ["No LLM spend in the selected window."];
  }

  const codeShare =
    summary.scoped_cost_usd / Math.max(summary.total_cost_usd, 0.0001);
  if (codeShare > 0.7) {
    suggestions.push(
      `This app is ${Math.round(codeShare * 100)}% of your spend. Other AI products (background agents, posthog_ai) are minor here.`,
    );
  }

  const codeTotal = summary.scoped_cost_usd;
  if (codeTotal > 0 && toolItems.length > 0) {
    const top = toolItems[0];
    if (top.share_of_scoped > 0.35 && top.tool) {
      suggestions.push(
        `${top.tool} drives ${Math.round(top.share_of_scoped * 100)}% of your spend in this app, averaging ${formatTokens(top.avg_input_tokens)} input tokens per call.`,
      );
    }
    const noToolRow = toolItems.find((r) => r.tool === null);
    if (noToolRow && noToolRow.share_of_scoped > 0.1) {
      suggestions.push(
        `${Math.round(noToolRow.share_of_scoped * 100)}% is spent on generations that take no tool action: pure text replies. Consider tighter prompts or stopping the agent earlier.`,
      );
    }
  }

  if (suggestions.length === 0) {
    suggestions.push(
      "Your spend is fairly evenly distributed across tools. No single hotspot stands out.",
    );
  }

  return suggestions;
}
