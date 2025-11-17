import { logger } from '../../../utils/logger'

export class AIService {
    private openaiApiKey: string | null

    constructor() {
        this.openaiApiKey = process.env.OPENAI_API_KEY || null
    }

    public async callAI(prompt: string, model: string, eventData: any): Promise<string | boolean> {
        if (!this.openaiApiKey) {
            throw new Error('OPENAI_API_KEY environment variable is not set')
        }

        logger.debug('🤖', `[AIService] Calling AI with prompt`, { prompt, model })

        try {
            // Call OpenAI API
            const response = await fetch('https://api.openai.com/v1/chat/completions', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${this.openaiApiKey}`,
                },
                body: JSON.stringify({
                    model: model || 'gpt-4-turbo',
                    messages: [
                        {
                            role: 'system',
                            content:
                                'You are an AI assistant analyzing event data in a workflow automation system. Respond concisely and directly. For yes/no questions, respond with just "true" or "false".',
                        },
                        {
                            role: 'user',
                            content: `${prompt}\n\nEvent data: ${JSON.stringify(eventData, null, 2)}`,
                        },
                    ],
                    temperature: 0.7,
                    max_tokens: 1000,
                }),
            })

            if (!response.ok) {
                const errorText = await response.text()
                throw new Error(`OpenAI API error: ${response.status} - ${errorText}`)
            }

            const data = await response.json()
            const content = data.choices?.[0]?.message?.content

            if (!content) {
                throw new Error('No response from AI')
            }

            // Try to parse as boolean for simple true/false responses
            const lowerContent = content.trim().toLowerCase()
            if (lowerContent === 'true' || lowerContent === 'false') {
                logger.debug('🤖', `[AIService] AI response (boolean)`, { response: lowerContent === 'true' })
                return lowerContent === 'true'
            }

            logger.debug('🤖', `[AIService] AI response`, { response: content.trim() })
            return content.trim()
        } catch (error: any) {
            logger.error('🤖', `[AIService] Error calling AI`, error)
            throw error
        }
    }
}
