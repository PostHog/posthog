import { CostContext, formatLLMCost } from '../utils'

export function CostBreakdownTooltip({
    costContext,
    children,
}: {
    costContext: CostContext
    children?: React.ReactNode
}): JSX.Element {
    const { inputCost, outputCost, requestCost, webSearchCost, totalCost } = costContext
    return (
        <div className="flex flex-col gap-0.5">
            {typeof inputCost === 'number' && <div>Input: {formatLLMCost(inputCost)}</div>}
            {typeof outputCost === 'number' && <div>Output: {formatLLMCost(outputCost)}</div>}
            {/* Request and web search costs are uncommon — hide zero values to reduce noise */}
            {typeof requestCost === 'number' && requestCost > 0 && <div>Request: {formatLLMCost(requestCost)}</div>}
            {typeof webSearchCost === 'number' && webSearchCost > 0 && (
                <div>Web search: {formatLLMCost(webSearchCost)}</div>
            )}
            <div className="font-semibold">Total: {formatLLMCost(totalCost)}</div>
            {children}
        </div>
    )
}
