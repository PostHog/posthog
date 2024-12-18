import api, { ApiConfig } from 'lib/api'

export const sidePanelMaxAPI = {
    async sendMessage(message: string): Promise<{ content: string }> {
        // Get or create session ID using sessionStorage
        let sessionId = sessionStorage.getItem('max_session_id')
        if (!sessionId) {
            sessionId = crypto.randomUUID()
            sessionStorage.setItem('max_session_id', sessionId)
        }

        const response = await api.createResponse(`/api/projects/${ApiConfig.getCurrentProjectId()}/max/chat/`, {
            message,
            role: 'user',
            session_id: sessionId,
        })

        if (!response.ok) {
            throw new Error('Failed to send message to Max')
        }

        const data = await response.json()
        return { content: data.content }
    },
}
