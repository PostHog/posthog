import { JSONContent } from '@tiptap/core'
import { v4 as uuidv4 } from 'uuid'

import {
    IconBug,
    IconCheckbox,
    IconComment,
    IconLetter,
    IconMessage,
    IconPeople,
    IconPlusSmall,
    IconTrending,
} from '@posthog/icons'

import { FormQuestionType } from './formTypes'

export interface FormTemplate {
    id: string
    name: string
    description: string
    icon: JSX.Element
    content: () => JSONContent
}

function questionNode(
    type: FormQuestionType,
    question: string,
    extra?: Record<string, unknown>
): { type: 'formQuestion'; attrs: { questionId: string; questionData: string } } {
    const id = uuidv4()
    return {
        type: 'formQuestion',
        attrs: {
            questionId: id,
            questionData: JSON.stringify({ type, question, optional: false, id, ...extra }),
        },
    }
}

function heading(text: string, level: number = 1): JSONContent {
    return { type: 'heading', attrs: { level }, content: [{ type: 'text', text }] }
}

function paragraph(text: string): JSONContent {
    return { type: 'paragraph', content: [{ type: 'text', text }] }
}

export const FORM_TEMPLATES: FormTemplate[] = [
    {
        id: 'waitlist',
        name: 'Waitlist',
        description: 'Collect signups for early access',
        icon: <IconLetter />,
        content: () => ({
            type: 'doc',
            content: [
                heading('Join the waitlist'),
                paragraph('Be the first to know when we launch. Sign up for early access below.'),
                questionNode(FormQuestionType.ShortText, 'Name'),
                questionNode(FormQuestionType.ShortText, 'Email address'),
                questionNode(FormQuestionType.LongText, 'What interests you most about this product?', {
                    optional: true,
                }),
            ],
        }),
    },
    {
        id: 'feedback',
        name: 'Feedback',
        description: 'Collect product or experience feedback',
        icon: <IconComment />,
        content: () => ({
            type: 'doc',
            content: [
                heading('Share your feedback'),
                paragraph("We'd love to hear about your experience. Your feedback helps us improve."),
                questionNode(FormQuestionType.StarRating, 'How would you rate your overall experience?', { scale: 5 }),
                questionNode(FormQuestionType.LongText, 'What went well? What could be improved?'),
            ],
        }),
    },
    {
        id: 'bug-report',
        name: 'Bug report',
        description: 'Let users report issues and bugs',
        icon: <IconBug />,
        content: () => ({
            type: 'doc',
            content: [
                heading('Report a bug'),
                paragraph("Found something broken? Let us know and we'll fix it."),
                questionNode(FormQuestionType.ShortText, 'What happened?'),
                questionNode(FormQuestionType.LongText, 'Steps to reproduce'),
                questionNode(FormQuestionType.SingleChoice, 'How severe is this issue?', {
                    choices: ['Critical - Blocks my work', 'Major - Significant impact', 'Minor - Small inconvenience'],
                    hasOpenChoice: false,
                }),
            ],
        }),
    },
    {
        id: 'feature-request',
        name: 'Feature request',
        description: 'Collect ideas from your users',
        icon: <IconPlusSmall />,
        content: () => ({
            type: 'doc',
            content: [
                heading('Request a feature'),
                paragraph("Have an idea for something we should build? We're all ears."),
                questionNode(FormQuestionType.ShortText, 'Feature name'),
                questionNode(FormQuestionType.LongText, 'Describe the feature and why you need it'),
                questionNode(FormQuestionType.SingleChoice, 'How important is this to you?', {
                    choices: ['Nice to have', 'Important', 'Critical'],
                    hasOpenChoice: false,
                }),
            ],
        }),
    },
    {
        id: 'user-research',
        name: 'User research',
        description: 'Recruit users for interviews and studies',
        icon: <IconPeople />,
        content: () => ({
            type: 'doc',
            content: [
                heading('Help us improve'),
                paragraph(
                    "We're looking for people to share their experience with us. Sessions are 30 minutes and you'll receive a thank-you gift."
                ),
                questionNode(FormQuestionType.ShortText, 'Name'),
                questionNode(FormQuestionType.ShortText, 'Email address'),
                questionNode(FormQuestionType.ShortText, 'What is your role?'),
                questionNode(FormQuestionType.LongText, 'How do you currently solve this problem?'),
                questionNode(FormQuestionType.SingleChoice, 'When are you available?', {
                    choices: ['This week', 'Next week', 'Flexible'],
                    hasOpenChoice: false,
                }),
            ],
        }),
    },
    {
        id: 'event-registration',
        name: 'Event registration',
        description: 'Sign up attendees for events',
        icon: <IconCheckbox />,
        content: () => ({
            type: 'doc',
            content: [
                heading('Event registration'),
                paragraph("Register for the event below. We'll send a confirmation to your email."),
                questionNode(FormQuestionType.ShortText, 'Full name'),
                questionNode(FormQuestionType.ShortText, 'Email address'),
                questionNode(FormQuestionType.MultipleChoice, 'Dietary requirements', {
                    choices: ['None', 'Vegetarian', 'Vegan', 'Gluten-free'],
                    hasOpenChoice: true,
                    optional: true,
                }),
            ],
        }),
    },
    {
        id: 'contact',
        name: 'Contact form',
        description: 'Let visitors get in touch',
        icon: <IconMessage />,
        content: () => ({
            type: 'doc',
            content: [
                heading('Contact us'),
                paragraph(
                    "Have a question or want to get in touch? Fill out the form below and we'll get back to you."
                ),
                questionNode(FormQuestionType.ShortText, 'Name'),
                questionNode(FormQuestionType.ShortText, 'Email address'),
                questionNode(FormQuestionType.ShortText, 'Subject'),
                questionNode(FormQuestionType.LongText, 'Message'),
            ],
        }),
    },
    {
        id: 'nps',
        name: 'NPS survey',
        description: 'Measure customer loyalty with NPS',
        icon: <IconTrending />,
        content: () => ({
            type: 'doc',
            content: [
                heading('How likely are you to recommend us?'),
                questionNode(
                    FormQuestionType.NumberRating,
                    'How likely are you to recommend us to a friend or colleague?',
                    {
                        scale: 10,
                        lowerBoundLabel: 'Not at all likely',
                        upperBoundLabel: 'Extremely likely',
                        isNpsQuestion: true,
                    }
                ),
                questionNode(FormQuestionType.LongText, "What's the main reason for your score?", { optional: true }),
            ],
        }),
    },
]

export const FEATURED_FORM_TEMPLATES = FORM_TEMPLATES.slice(0, 4)
