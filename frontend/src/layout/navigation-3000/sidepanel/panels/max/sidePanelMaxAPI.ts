import api from 'lib/api'

interface RateLimit {
    limit: number
    remaining: number
    reset: string
}

interface RateLimits {
    requests: RateLimit
    input_tokens: RateLimit
    output_tokens: RateLimit
}

interface MaxResponse {
    content: string
    rate_limits: RateLimits
}

export const sidePanelMaxAPI = {
    async sendMessage(message: string): Promise<MaxResponse> {
        // Get or create session ID using sessionStorage
        let sessionId = sessionStorage.getItem('max_session_id')
        if (!sessionId) {
            sessionId = crypto.randomUUID()
            sessionStorage.setItem('max_session_id', sessionId)
        }

        const response = await api.createResponse(`/max/chat/`, {
            message,
            role: 'user',
            session_id: sessionId,
        })

        if (!response.ok) {
            throw new Error('Failed to send message to Max')
        }

        const data = await response.json()
        return {
            content: data.content,
            rate_limits: data.rate_limits,
        }
    },
}
