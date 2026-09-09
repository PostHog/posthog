// Insurance against a recipe that expands a large event into unbounded work. Recipes are
// team-authored and now also run headless (the MCP tool compiles a candidate and runs it
// against the real event), so a pathological one has to fail fast instead of pinning the
// process. Both ceilings sit far above what any renderable trace produces.
const MAX_OPERATIONS = 250_000
const MAX_MESSAGES = 25_000

export class ExecutionBudget {
    // Input nodes dispatched, plus array items a followup expands over.
    private operations = 0
    // Messages materialized across the whole run.
    private messages = 0

    // Charged per run, not per pipeline: the browser keeps one normalizer for the session.
    reset(): void {
        this.operations = 0
        this.messages = 0
    }

    chargeOperations(count: number): void {
        this.operations += count
        if (this.operations > MAX_OPERATIONS) {
            throw new Error(
                `RecipeNormalizer: exceeded the operation budget (${MAX_OPERATIONS}) — a recipe expands this event into too much work`
            )
        }
    }

    chargeMessages(count: number): void {
        this.messages += count
        if (this.messages > MAX_MESSAGES) {
            throw new Error(
                `RecipeNormalizer: exceeded the message budget (${MAX_MESSAGES}) — a recipe expands this event into too many messages`
            )
        }
    }
}
