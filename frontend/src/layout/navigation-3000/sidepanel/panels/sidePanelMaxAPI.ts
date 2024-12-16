import { ApiConfig } from 'lib/api'

let currentSessionId: string | null = null

export const sidePanelMaxAPI = {
    async sendMessage(message: string): Promise<{ content: string }> {
        const projectId = ApiConfig.getCurrentProjectId()
        if (!projectId) {
            throw new Error('Project ID is required but not available')
        }

        const response = await fetch(`/api/projects/${projectId}/max/chat/`, {
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
