import { makeReport } from 'products/signals/frontend/inbox/__mocks__/inboxMocks'

import { feedReportFacts } from './todayFeedReport'

const pullRequest = { url: 'https://github.com/example/app/pull/42', state: 'open' }
const report = makeReport({ id: 'r-1', suggested_prompts: ['Why did it break?'] })
const preview = { sources: null, lead: null, metric: null, pullRequest }

describe('feedReportFacts', () => {
    test.each([
        { title: 'Fix the checkout', done: false, number: '42', prompt: 'Why did it break?' },
        { title: 'Review PR #42', done: false, number: null, prompt: 'Why did it break?' },
        { title: 'Fix the checkout', done: true, number: '42', prompt: null },
    ])('shows the pull request $number and the prompt $prompt for "$title"', ({ title, done, number, prompt }) => {
        const facts = feedReportFacts(report, title, preview, done)
        expect(facts.pullRequest?.number ?? null).toEqual(number)
        expect(facts.prompt).toEqual(prompt)
    })
})
