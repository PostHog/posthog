export const roleMap: Record<string, string> = {
    user: 'user',
    human: 'user',

    assistant: 'assistant',
    model: 'assistant',
    ai: 'assistant',
    bot: 'assistant',

    system: 'system',
    instructions: 'system',
    context: 'system',
}

export function normalizeRole(rawRole: unknown, fallback: string): string {
    if (typeof rawRole !== 'string') {
        return fallback
    }
    const lowercased = rawRole.toLowerCase()
    return roleMap[lowercased] || lowercased
}

// Synthetic role used to surface the `$ai_tools` payload as a pseudo-message
export const AVAILABLE_TOOLS_ROLE = 'available tools'
