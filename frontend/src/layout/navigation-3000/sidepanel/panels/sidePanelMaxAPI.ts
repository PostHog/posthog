import { ApiConfig } from 'lib/api'

export const sidePanelMaxAPI = {
    async sendMessage(message: string): Promise<{ content: string }> {
        const projectId = ApiConfig.getCurrentProjectId()
        if (!projectId) {
            throw new Error('Project ID is required but not available')
        }

        // Get or create session ID using sessionStorage
        let sessionId = sessionStorage.getItem('max_session_id')
        if (!sessionId) {
            sessionId = crypto.randomUUID()
            sessionStorage.setItem('max_session_id', sessionId)
        }

        const isDevelopment = process.env.NODE_ENV === 'development'
        const baseUrl = isDevelopment ? 'http://localhost:3001' : ''

        const response = await fetch(`${baseUrl}/api/projects/${projectId}/max/chat/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                message,
                role: 'user',
                session_id: sessionId,
            }),
        })

        if (!response.ok) {
            throw new Error('Failed to send message to Max')
        }

        const data = await response.json()
        return { content: data.content }
    },
}
