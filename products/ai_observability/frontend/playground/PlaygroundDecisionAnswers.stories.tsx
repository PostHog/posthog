import { Meta, StoryObj } from '@storybook/react'

import { PlaygroundDecisionAnswers } from './PlaygroundDecisionAnswers'

const meta: Meta<typeof PlaygroundDecisionAnswers> = {
    title: 'Scenes-App/AI Observability/Playground Decision Answers',
    component: PlaygroundDecisionAnswers,
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta
type Story = StoryObj<typeof PlaygroundDecisionAnswers>

export const EveryAnswerType: Story = {
    render: function Render() {
        return (
            <div className="max-w-150 text-xs">
                <PlaygroundDecisionAnswers
                    questions={[
                        { id: 'upset', type: 'noul', instructions: 'Is the user upset?', options: [] },
                        {
                            id: 'topic',
                            type: 'choice',
                            instructions: 'What is the message about?',
                            options: [
                                { id: 'a', name: 'billing', description: 'Invoices and charges' },
                                { id: 'b', name: 'bug', description: '' },
                            ],
                        },
                        {
                            id: 'urgency',
                            type: 'score',
                            instructions: 'How urgent is it?',
                            options: [
                                { id: 'c', name: 'Low', description: '' },
                                { id: 'd', name: 'Medium', description: '' },
                                { id: 'e', name: 'High', description: '' },
                            ],
                        },
                        { id: 'language', type: 'noul', instructions: 'Is it written in French?', options: [] },
                    ]}
                    result={{
                        model: 'jev-1.13',
                        answers: {
                            upset: {
                                type: 'noul',
                                probability: 0.83,
                                choice: null,
                                score: null,
                                confidence: null,
                                probabilities: null,
                            },
                            topic: {
                                type: 'choice',
                                probability: null,
                                choice: 'billing',
                                score: null,
                                confidence: 0.7,
                                probabilities: { billing: 0.67, bug: 0.33 },
                            },
                            urgency: {
                                type: 'score',
                                probability: null,
                                choice: null,
                                score: 0.6,
                                confidence: 0.55,
                                probabilities: { '0': 0.57, '1': 0.29, '2': 0.14 },
                            },
                            language: {
                                type: 'refusal',
                                probability: null,
                                choice: null,
                                score: null,
                                confidence: null,
                                probabilities: null,
                            },
                        },
                        input_tokens: 37,
                        output_tokens: null,
                    }}
                />
            </div>
        )
    },
}
