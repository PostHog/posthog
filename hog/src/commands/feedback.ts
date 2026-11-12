import { defineCommand } from '@/core/command'
import { EXIT_FAILURE, EXIT_USAGE, HogError } from '@/core/errors'

// Its properties match the MCP server's `mcp feedback submitted` event, so one query can read both.
export const FEEDBACK_EVENT = 'cli feedback submitted'

const TYPES = ['cli', 'product', 'docs', 'mcp', 'other'] as const
const SENTIMENTS = ['positive', 'neutral', 'negative', 'mixed'] as const
const MAX_LENGTH = 5000
const MAX_SUMMARY_LENGTH = 200

type FeedbackType = (typeof TYPES)[number]
type Sentiment = (typeof SENTIMENTS)[number]

interface Feedback {
    summary: string
    details: string | undefined
}

function parseFeedback(text: string): Feedback {
    const trimmed = text.trim()
    if (trimmed.length > MAX_LENGTH) {
        throw new HogError(
            'feedback_too_long',
            `The feedback is ${trimmed.length} characters, and hog sends up to ${MAX_LENGTH}.`,
            'Shorten it, then run the command again.',
            EXIT_USAGE
        )
    }

    const firstLine = trimmed.split('\n', 1)[0]!.trim()
    const summary =
        firstLine.length > MAX_SUMMARY_LENGTH ? `${firstLine.slice(0, MAX_SUMMARY_LENGTH - 3)}...` : firstLine
    return { summary, details: trimmed === summary ? undefined : trimmed }
}

export default defineCommand({
    description: 'Send feedback about hog or PostHog to the PostHog team',
    args: {
        message: {
            description: 'What you want to tell the team, or - to read it from stdin. The first line is the summary',
            optional: true,
            stdin: true,
        },
    },
    options: {
        type: {
            type: 'string',
            choices: TYPES,
            description:
                'What the feedback is about: hog itself (cli), a PostHog product, the docs, the MCP server, or other',
        },
        sentiment: { type: 'string', choices: SENTIMENTS, description: 'How it went' },
        area: {
            type: 'string',
            placeholder: 'name',
            description: 'The product or command it is about, like "session replay" or "hog query run"',
        },
        suggestion: { type: 'string', placeholder: 'text', description: 'What would make it better' },
        dryRun: { type: 'boolean', description: 'Show what hog would send without sending it' },
    },
    writes: true,
    notes: 'Feedback goes to the PostHog team even with telemetry off. Then it carries no account, organization or install ID.',
    examples: [
        'hog feedback "hog query run cuts off long values" --sentiment negative',
        'hog feedback "Session replay loads fast now" --type product --area "session replay" --sentiment positive',
        'hog feedback - < notes.txt',
    ],

    async run({ args, options, ctx }) {
        let text = args.message
        if (text === undefined) {
            if (!ctx.prompts) {
                throw new HogError(
                    'missing_feedback',
                    'There is no feedback to send.',
                    'Pass it as an argument, like `hog feedback "hog query run cuts off long values"`, or - to read it from stdin.',
                    EXIT_USAGE
                )
            }
            text = await ctx.prompts.text('What do you want to tell the PostHog team?', {
                validate: (value) => (value.trim() ? undefined : 'Write your feedback, or press Ctrl-C to cancel.'),
            })
        }

        const feedback = parseFeedback(text)
        const type: FeedbackType = options.type ?? 'cli'
        const sentiment: Sentiment | undefined = options.sentiment
        const properties = {
            feedback_summary: feedback.summary,
            feedback_type: type,
            feedback_sentiment: sentiment,
            feedback_product_area: options.area,
            feedback_details: feedback.details,
            feedback_suggested_improvement: options.suggestion,
        }

        if (options.dryRun) {
            return { sent: false, dryRun: true, identified: false, type, sentiment: sentiment ?? null, ...feedback }
        }

        // Loads a stored login, so feedback from a logged-in person belongs to their PostHog user.
        await ctx.credentials().catch(() => undefined)
        const { sent, identified } = await ctx.telemetry.send(FEEDBACK_EVENT, properties, ctx.globals.debug === true)
        if (!sent) {
            throw new HogError(
                'feedback_not_sent',
                "hog couldn't send your feedback.",
                'Check your network connection, then run the command again.',
                EXIT_FAILURE
            )
        }
        return { sent: true, dryRun: false, identified, type, sentiment: sentiment ?? null, ...feedback }
    },
    human({ result, out }) {
        if (result.dryRun) {
            out.report({
                result: 'Dry run: this feedback would go to the PostHog team. Nothing was sent',
                status: 'unchanged',
                effects: [
                    `${out.style('Summary:', 'bold')} ${result.summary}`,
                    `${out.style('Type:', 'bold')} ${result.type}`,
                ],
            })
            return
        }
        out.report({
            result: 'Sent your feedback to the PostHog team. Thank you.',
            notes: result.identified
                ? []
                : ['It was sent without your PostHog account, so the team can see what you said but not who said it.'],
        })
    },
    agent({ result, out }) {
        out.json(result)
    },

    telemetry: ({ result }) => ({ feedback_type: result.type, sentiment: result.sentiment, dry_run: result.dryRun }),
})
