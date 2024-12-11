const MAX_API_HOST = 'http://localhost:3000' // Default port used in sidebar_max_AI.py

let currentSessionId: string | null = null

export const sidePanelMaxAPI = {
    async sendMessage(message: string): Promise<{ content: string }> {
        const response = await fetch(`${MAX_API_HOST}/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                message,
                role: 'user',
                session_id: currentSessionId,
            }),
        })

        if (!response.ok) {
            throw new Error('Failed to send message to Max')
        }

        const data = await response.json()
        currentSessionId = data.session_id // Store the session ID for next request
        return { content: data.content }
    },
}
