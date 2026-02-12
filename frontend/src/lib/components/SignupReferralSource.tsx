import { useState } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { LemonField } from 'lib/lemon-ui/LemonField'

// Used to trigger the AI prompt when the user enters an AI-related referral source. This is a simple heuristic and can be adjusted as needed.
const AI_REFERRAL_PATTERNS = [
    // AI labs
    'openai',
    'open ai',
    'anthropic',
    'perplexity',
    'xai',
    'mistral',
    'eleven labs',
    'elevenlabs',
    'meta ai',
    'anysphere',
    'groq',
    // AI models and tooling
    'chatgpt',
    'chat gpt',
    'gpt',
    'claude',
    'gemini',
    'bard',
    'copilot',
    'deepseek',
    'deep seek',
    'grok',
    'codex',
    'cursor',
    'manus',
    'windsurf',
    'antigravity',
    'cline',
    // LLM coding platforms
    'replit',
    'repl it',
    'lovable',
    'hercules',
    'vercel',
    'v0',
    'bolt',
    'rork',
    'retool',
    'figma make',
    // Adjacent words
    'ai',
    'llm',
    'large language model',
    'artificial intelligence',
    'assistant',
    'chat',
    'vibecoding',
    'vibe coding',
    'mcp',
]
const AI_REFERRAL_PATTERN = new RegExp(`\\b(${AI_REFERRAL_PATTERNS.join('|')})\\b`, 'i')

export default function SignupReferralSource({ disabled }: { disabled: boolean }): JSX.Element {
    const [showAIPrompt, setShowAIPrompt] = useState(false)

    return (
        <>
            <LemonField name="referral_source" label="Where did you hear about us?" showOptional>
                {({ value, onChange }) => (
                    <LemonInput
                        className="ph-ignore-input"
                        data-attr="signup-referral-source"
                        placeholder=""
                        disabled={disabled}
                        value={value ?? ''}
                        onChange={(val: string) => {
                            onChange(val)
                            setShowAIPrompt(AI_REFERRAL_PATTERN.test(val))
                        }}
                    />
                )}
            </LemonField>
            <AnimatedCollapsible collapsed={!showAIPrompt}>
                <LemonField
                    name="referral_source_ai_prompt"
                    label="What prompt or search led you to PostHog?"
                    help="Paste the prompt or search queries if you remember, even roughly"
                    showOptional
                >
                    <LemonInput
                        className="ph-ignore-input"
                        data-attr="signup-referral-source-ai-prompt"
                        placeholder="e.g. Product analytics tool with error tracking"
                        disabled={disabled}
                    />
                </LemonField>
            </AnimatedCollapsible>
        </>
    )
}
