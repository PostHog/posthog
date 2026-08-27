interface CodeExampleParams {
    surveyId?: string
    followUpEnabled: boolean
}

export function getReactExample({ surveyId = 'your-survey-id', followUpEnabled }: CodeExampleParams): string {
    return `// requires @posthog/react 1.7.1+ (bundled with posthog-js 1.345.1+)
import { useThumbSurvey } from '@posthog/react/surveys'

function HedgehogBotResponse({ traceId }: { traceId: string }) {
  const { respond, response${followUpEnabled ? ', triggerRef' : ''} } = useThumbSurvey({
    surveyId: '${surveyId}', // ID for the survey you just created
    properties: {
      $ai_trace_id: traceId, // your generated trace ID
      // add any other custom properties here
    },
  })

  return (
    <div>
      <ChatBubble>You're absolutely right! I should have been using PostHog all along.</ChatBubble>

      ${followUpEnabled ? '<div ref={triggerRef}> {/* PostHog followup pop-up anchors to triggerRef */}' : '<div>'}
        <p>Was this response helpful?</p>
        <button className={response === 'up' ? 'active' : ''} onClick={() => respond('up')}>👍</button>
        <button className={response === 'down' ? 'active' : ''} onClick={() => respond('down')}>👎</button>
      </div>

    </div>
  )
}`
}

interface Prop {
    key: string
    value: string
    comment?: string
}

const generateProps = (props: Prop[], indent = 2): string => {
    const spaces = ' '.repeat(indent)
    return props
        .map(({ key, value, comment }) => `${spaces}${key}: ${value},${comment ? ` // ${comment}` : ''}`)
        .join('\n')
}

export function getManualCaptureExample({ surveyId = 'your-survey-id', followUpEnabled }: CodeExampleParams): string {
    const thumbsProps: Prop[] = [
        { key: '$survey_id', value: `'${surveyId}'`, comment: 'ID for the survey you just created' },
        { key: '$survey_response', value: 'rating' },
        { key: '$ai_trace_id', value: 'traceId', comment: 'your generated trace ID' },
        ...(followUpEnabled
            ? [
                  {
                      key: '$survey_submission_id',
                      value: 'submissionId',
                      comment: 'unique ID to link thumbs + follow-up',
                  },
                  { key: '$survey_completed', value: '!expectsFollowUp' },
              ]
            : []),
    ]

    const surveyShownProps: Prop[] = [
        { key: '$survey_id', value: `'${surveyId}'` },
        { key: '$ai_trace_id', value: 'traceId' },
    ]

    const ratingLine = 'const rating = clickedThumbsUp ? 1 : 2 // 1 = thumbs up, 2 = thumbs down'

    const preamble = followUpEnabled
        ? `// Generate a unique ID to link \`survey sent\` events into a single user feedback event
const submissionId = crypto.randomUUID()

${ratingLine}
// Only a thumbs down opens the follow-up, so a thumbs up completes the submission here
const expectsFollowUp = rating === 2

`
        : `${ratingLine}

`

    const base = `// (Optional) Track when the survey is shown to the user
posthog.capture('survey shown', {
${generateProps(surveyShownProps)}
})

${preamble}// When user clicks thumbs up/down, send a survey event
posthog.capture('survey sent', {
${generateProps(thumbsProps)}
})`

    if (followUpEnabled) {
        const followUpProps: Prop[] = [
            { key: '$survey_id', value: `'${surveyId}'` },
            { key: '$survey_response', value: 'rating', comment: 're-send the thumbs response so it still shows' },
            { key: '$survey_response_1', value: 'followUpText', comment: "'' if the user dismissed the follow-up" },
            { key: '$ai_trace_id', value: 'traceId' },
            {
                key: '$survey_submission_id',
                value: 'submissionId',
                comment: "must match the previous event's $survey_submission_id",
            },
            { key: '$survey_completed', value: 'true' },
        ]

        return (
            base +
            `

// When the follow-up closes, send the answers so far.
// Send it even on dismissal, or PostHog drops the submission and the thumbs rating with it.
posthog.capture('survey sent', {
${generateProps(followUpProps)}
})`
        )
    }

    return base
}
