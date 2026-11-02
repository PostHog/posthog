import { Field as KeaField } from 'kea-forms'

import { LemonInput } from '@posthog/lemon-ui'

import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { LemonField } from 'lib/lemon-ui/LemonField'

// Used to trigger the AI prompt when the user enters an AI-related referral source. This is a simple heuristic and can be adjusted as needed.
const AI_REFERRAL_PATTERNS = [
    // AI labs
    'open ?ai',
    'anthropic',
    'perplexity',
    'x ?ai',
    'mistral',
    'eleven ?labs',
    'meta ?ai',
    'anysphere',
    'groq',
    'z.ai',
    // AI models and tooling
    'chat ?gpt',
    'gpt',
    'claude',
    'claud', // common typo
    'opus',
    'sonnet',
    'haiku',
    'gemini',
    'flash',
    'bard',
    'copilot',
    'deep ?seek',
    'grok',
    'qwen',
    'kimi',
    'devstral',
    'nemo',
    'composer',
    'codex',
    'cursor',
    'manus',
    'windsurf',
    'antigravity',
    'cline',
    'dia',
    // LLM coding platforms
    'repl ?it',
    'lovable',
    'hercules',
    'vercel',
    'v0',
    'bolt',
    'rork',
    'retool',
    'figma ?make',
    'poke',
    'clawdbot',
    'moltbot',
    'openclaw',
    'ai.com',
    // Adjacent words
    'ai',
    'llm',
    'large language model',
    'artificial intelligence',
    'assistant',
    'chat',
    'vibe ?coding',
    'mcp',
    // Non-English equivalents
    'ia', // Spanish, Italian, Portuguese, French abbreviation for AI
    'ki', // German abbreviation (Künstliche Intelligenz)
]
const AI_REFERRAL_PATTERN = new RegExp(`\\b(${AI_REFERRAL_PATTERNS.join('|')})\\b`, 'i')

// Used to trigger the influencer prompt when the user mentions a social network or creator channel. This is a simple heuristic and can be adjusted as needed.
// Longer triggers allow the word to continue (\w*) so the field does not close mid-word
// ("Insta" → "Instag" → "Instagram") and plurals match. One-or-two-letter abbreviations
// stay exact words so "max" or "ignore" do not match.
const SOCIAL_REFERRAL_PATTERNS = [
    // Social networks
    'insta\\w*',
    'ig',
    'tik ?tok\\w*',
    'you ?tub\\w*',
    'yt',
    'twitter',
    'tweet\\w*',
    'x',
    'x.com',
    'linked ?in',
    'facebook',
    'fb',
    'threads',
    'blue ?sky',
    'mastodon',
    'reddit\\w*',
    'twitch',
    'snap ?chat\\w*',
    'discord',
    'telegram',
    'whats ?app',
    'we ?chat',
    'weibo',
    'pinterest',
    'social ?media',
    'social ?network\\w*',
    // Creator channels
    'influencer\\w*',
    'creator\\w*',
    'content ?creator\\w*',
    'streamer\\w*',
    'blogger\\w*',
    'vlogger\\w*',
    'podcast\\w*',
    'news ?letter\\w*',
    'substack',
]
const SOCIAL_REFERRAL_PATTERN = new RegExp(`\\b(${SOCIAL_REFERRAL_PATTERNS.join('|')})\\b`, 'i')

// 'chat' also names social features ("Twitch chat", "Discord chat"), so it does not count
// toward the AI tie-break when a social trigger is present. Any other AI trigger still wins.
const AI_TIEBREAK_PATTERN = new RegExp(
    `\\b(${AI_REFERRAL_PATTERNS.filter((pattern) => pattern !== 'chat').join('|')})\\b`,
    'i'
)

// At most one follow-up shows at a time
export function getReferralFollowUp(referralSource: string): 'ai' | 'influencer' | null {
    const matchesAi = AI_REFERRAL_PATTERN.test(referralSource)
    const matchesSocial = SOCIAL_REFERRAL_PATTERN.test(referralSource)
    if (matchesAi && matchesSocial) {
        return AI_TIEBREAK_PATTERN.test(referralSource) ? 'ai' : 'influencer'
    }
    if (matchesAi) {
        return 'ai'
    }
    if (matchesSocial) {
        return 'influencer'
    }
    return null
}

export default function SignupReferralSource({ disabled }: { disabled: boolean }): JSX.Element {
    return (
        // A collapsed follow-up placed directly in the form would still take a form gap, so the
        // follow-ups share this column and carry their own top padding instead
        <div className="flex flex-col">
            <LemonField name="referral_source" label="Where did you hear about us?" showOptional>
                {({ value, onChange }) => (
                    <LemonInput
                        className="ph-ignore-input"
                        data-attr="signup-referral-source"
                        placeholder="e.g. a colleague, or a web search"
                        disabled={disabled}
                        value={value ?? ''}
                        onChange={onChange}
                    />
                )}
            </LemonField>
            {/* Subscribing here rather than in the parent keeps a keystroke from re-rendering the
                whole signup panel. */}
            <KeaField name="referral_source" noStyle>
                {({ value }) => {
                    const followUp = getReferralFollowUp(value ?? '')
                    return (
                        <>
                            <AnimatedCollapsible collapsed={followUp !== 'ai'}>
                                <LemonField
                                    className="pt-4"
                                    name="referral_source_ai_prompt"
                                    label="What prompt or search led you to PostHog?"
                                    help="Paste the prompt or search queries if you remember, even roughly"
                                    showOptional
                                >
                                    <LemonInput
                                        className="ph-ignore-input"
                                        data-attr="signup-referral-source-ai-prompt"
                                        placeholder="e.g. Product analytics tool with error tracking"
                                        // Also disabled while collapsed, to keep the hidden input out of the tab order
                                        disabled={disabled || followUp !== 'ai'}
                                    />
                                </LemonField>
                            </AnimatedCollapsible>
                            <AnimatedCollapsible collapsed={followUp !== 'influencer'}>
                                <LemonField
                                    className="pt-4"
                                    name="referral_source_influencer"
                                    label="Which account or person led you to PostHog?"
                                    help="Name the account, channel, or person if you remember"
                                    showOptional
                                >
                                    <LemonInput
                                        className="ph-ignore-input"
                                        data-attr="signup-referral-source-influencer"
                                        placeholder="e.g. a YouTube channel, or an X account"
                                        // Also disabled while collapsed, to keep the hidden input out of the tab order
                                        disabled={disabled || followUp !== 'influencer'}
                                    />
                                </LemonField>
                            </AnimatedCollapsible>
                        </>
                    )
                }}
            </KeaField>
        </div>
    )
}
