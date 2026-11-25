// Prompt text can carry text from a customer's own users, including backticks. A fence longer than every
// backtick run in the text cannot be closed from inside it, so the text cannot break out of the code block
// and pose as instructions to the agent.
export function fenceUntrusted(text: string): string {
    const longestRun = (text.match(/`+/g) ?? []).reduce((longest, run) => Math.max(longest, run.length), 0)
    const fence = '`'.repeat(Math.max(3, longestRun + 1))
    return `${fence}\n${text}\n${fence}`
}
