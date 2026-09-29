import {
    TodayAgentOption,
    TodayBriefingSegment,
    TodayEvidenceKind,
    TodayFollowUpOption,
    TodayMenuOption,
    TodayRecentError,
    TodayRecording,
    TodayScenario,
    TodayScenarioId,
    TodayReport,
} from './todayTypes'

/**
 * Sample reports for a project with no Self-driving reports yet, so the Today layout can be tried end to end.
 * Everything here describes the Hedgebox demo project and is invented.
 */
export const SAMPLE_REPORTS: TodayReport[] = [
    {
        id: 'pr',
        title: 'Review PR #9123',
        meta: 'Safari checkout fix · 2h ago',
        color: '#ff5c1c',
        icon: 'pr',
        heading: 'The Safari checkout fix is ready for review.',
        paragraphs: [
            'Tuesday’s deploy stopped some Safari users before payment. The checkout sent an empty billing address to the payment service.',
            'PR #9123 restores the address before payment is submitted. The change is small, tested, and ready for you.',
        ],
        evidence: [
            {
                product: 'Error tracking',
                value: '1,284 events',
                detail: 'The same TypeError started after deploy #4821.',
                color: '#e58e00',
                kind: 'error',
            },
            {
                product: 'Session replay',
                value: '38 recordings',
                detail: 'Safari users stop after they submit payment.',
                color: '#0457ff',
                kind: 'replay',
            },
            {
                product: 'Product analytics',
                value: '−12 points',
                detail: 'Safari completion fell while Chrome stayed flat.',
                color: '#2f80fa',
                kind: 'analytics',
            },
            {
                product: 'GitHub',
                value: 'PR #9123',
                detail: 'The fix restores the missing billing address.',
                color: '#ff5c1c',
                kind: 'code',
            },
        ],
        action: {
            primary: 'Merge PR #9123',
            status: 'CI passed · 18 checks',
            tone: 'success',
            confirmation: 'Merge requested for PR #9123.',
            done: 'Merged',
            pr: '#9123',
            followUp: {
                title: 'Did the Safari checkout fix land?',
                summary:
                    'I’ll check Safari checkout completion and the formatAddress error rate since PR #9123 merged. If either hasn’t recovered, I’ll reopen this with what changed.',
            },
        },
    },
    {
        id: 'exp',
        title: 'Ship one-page checkout',
        meta: '95% chance to win',
        color: '#35b14e',
        icon: 'experiment',
        heading: 'One-page checkout won. It is safe to ship.',
        paragraphs: [
            'The shorter checkout completed more often than the current flow. It did not increase refunds, support requests, or payment errors.',
            'The result passed the team’s decision threshold. You can send the winning flow to everyone today.',
        ],
        evidence: [
            {
                product: 'Experiments',
                value: '95% likely',
                detail: 'The one-page version is the likely winner.',
                color: '#35b14e',
                kind: 'experiment',
            },
            {
                product: 'Product analytics',
                value: '+6.4%',
                detail: 'Checkout completion rose from 54.1% to 57.6%.',
                color: '#2f80fa',
                kind: 'analytics',
            },
            {
                product: 'Session replay',
                value: 'Fewer exits',
                detail: 'People no longer pause between address and payment.',
                color: '#f0a512',
                kind: 'replay',
            },
            {
                product: 'Feature flags',
                value: 'Ready',
                detail: 'The winning variant can reach everyone now.',
                color: '#2fabca',
                kind: 'flag',
            },
        ],
        action: {
            primary: 'Ship one-page checkout',
            status: 'Ready · 95% likely to win',
            tone: 'success',
            confirmation: 'The winning checkout is ready to ship.',
            icon: 'ship',
            done: 'Shipped to 100%',
            run: {
                loading: 'Rolling out…',
                steps: [
                    'Turning on one-page-checkout for 10% of users…',
                    'Guardrails holding. Rolling out to 50%…',
                    'Rolling out to everyone…',
                ],
                result: 'Shipped. The old checkout stays behind the flag for 7 days in case you need to roll back.',
                live: 'Live for 100% of users',
            },
            followUp: {
                title: 'Did the win hold at 100%?',
                summary:
                    'I’ll check checkout completion, refunds and payment errors now that everyone gets the one-page checkout. If completion slips below the experiment’s 57.6%, I’ll flag it here.',
            },
        },
    },
    {
        id: 'safari',
        title: 'Watch 38 Safari recordings',
        meta: 'Checkout · Safari 17',
        color: '#0457ff',
        icon: 'replay',
        heading: 'Safari users reach payment, then get stuck.',
        paragraphs: [
            'The recordings show the same sequence. A person enters a card, submits payment, and sees no progress.',
            'The problem affects Safari 17 after Tuesday’s deploy. Chrome sessions continue through the same step.',
        ],
        evidence: [
            {
                product: 'Session replay',
                value: '38 sessions',
                detail: 'Every sampled session stalls after payment.',
                color: '#0457ff',
                kind: 'replay',
            },
            {
                product: 'Product analytics',
                value: '49% complete',
                detail: 'Safari trails Chrome by 13 points.',
                color: '#2f80fa',
                kind: 'analytics',
            },
            {
                product: 'Error tracking',
                value: 'address.ts:42',
                detail: 'The billing address is empty at submission.',
                color: '#e58e00',
                kind: 'error',
            },
            {
                product: 'Data warehouse',
                value: 'Safari 17',
                detail: 'Older Safari versions stay near their baseline.',
                color: '#8567ff',
                kind: 'warehouse',
            },
        ],
        action: {
            primary: 'Ship it',
            status: '38 matching recordings',
            tone: 'info',
            confirmation: 'The fix is shipping.',
            waitingOn: 'Agent is writing PR',
            icon: 'ship',
        },
    },
    {
        id: 'error',
        title: 'Triage the formatAddress TypeError',
        meta: '412 users · 1,284 events',
        color: '#e58e00',
        icon: 'error',
        heading: 'One new error is blocking checkout completion.',
        paragraphs: [
            'The error begins when checkout formats an empty billing address. It started with deploy #4821 and appears only after payment submission.',
            'Four hundred and twelve people saw it. The same error also explains the Safari conversion drop.',
        ],
        evidence: [
            {
                product: 'Error tracking',
                value: '1,284 events',
                detail: 'TypeError in formatAddress at address.ts:42.',
                color: '#e58e00',
                kind: 'error',
            },
            {
                product: 'Product analytics',
                value: '412 users',
                detail: 'Most affected users arrived from Safari.',
                color: '#2f80fa',
                kind: 'analytics',
            },
            {
                product: 'Session replay',
                value: '19 sampled',
                detail: 'The submit button stops after one click.',
                color: '#f0a512',
                kind: 'replay',
            },
            {
                product: 'Data warehouse',
                value: 'Deploy #4821',
                detail: 'The first event arrived six minutes after release.',
                color: '#8567ff',
                kind: 'warehouse',
            },
        ],
        action: {
            primary: 'Merge PR #9131',
            status: 'PR ready · 412 users affected',
            tone: 'warning',
            confirmation: 'Merge requested for PR #9131.',
            done: 'Merged',
            pr: '#9131',
            advisory: {
                from: 'Adversarial agent',
                text: 'suggests a human review before this ships. The fix touches payment submission, so test it by hand on Safari 17 too.',
            },
            followUp: {
                title: 'Did the formatAddress error stop?',
                summary:
                    'I’ll confirm the TypeError stopped firing after PR #9131 merged and that no new payment errors took its place, including the hand test on Safari 17 the adversarial agent asked for.',
            },
        },
    },
    {
        id: 'llm',
        title: 'Check which model summarize-doc uses',
        meta: 'LLM cost per user +31%',
        color: '#a737d2',
        icon: 'llm',
        heading: 'Document summaries became more expensive overnight.',
        paragraphs: [
            'The summarize-doc workflow now spends 31% more per active user. Usage stayed flat, so higher traffic does not explain the change.',
            'Most of the increase comes from a model change and longer prompts. The quality score did not improve.',
        ],
        evidence: [
            {
                product: 'LLM analytics',
                value: '+31% cost',
                detail: 'Cost rose while the number of summaries stayed flat.',
                color: '#a737d2',
                kind: 'trace',
            },
            {
                product: 'Tracing',
                value: '2.4× tokens',
                detail: 'The new prompt repeats the source document.',
                color: '#06b6d4',
                kind: 'trace',
            },
            {
                product: 'Product analytics',
                value: 'Usage flat',
                detail: 'The same number of people used summaries.',
                color: '#2f80fa',
                kind: 'analytics',
            },
            {
                product: 'Data warehouse',
                value: 'summarize-doc',
                detail: 'One workflow accounts for 84% of the increase.',
                color: '#8567ff',
                kind: 'warehouse',
            },
        ],
        action: {
            primary: 'Merge revert PR #9140',
            status: 'Revert ready · cost per user +31%',
            tone: 'warning',
            confirmation: 'Merge requested for PR #9140.',
            done: 'Merged',
            pr: '#9140',
            followUp: {
                title: 'Did cost per user come back down?',
                summary:
                    'I’ll compare summarize-doc cost per user and quality scores since the revert in PR #9140 merged. If cost hasn’t dropped, I’ll look for the next biggest spender.',
            },
        },
    },
    {
        id: 'nps',
        title: 'Read 23 pricing complaints',
        meta: 'Completed · NPS 32',
        color: '#6d4fff',
        icon: 'survey',
        heading: 'Pricing is the main reason detractors hesitate.',
        paragraphs: [
            'Twenty-three detractors mention pricing in their survey response. Most of them visited the new pricing page before they replied.',
            'They understand the product, but they cannot predict the bill. The confusion is strongest among small teams with growing data volume.',
        ],
        evidence: [
            {
                product: 'Surveys',
                value: 'NPS 32',
                detail: 'Twenty-three of 61 detractors mention pricing.',
                color: '#6d4fff',
                kind: 'survey',
            },
            {
                product: 'Customer analytics',
                value: 'Small teams',
                detail: 'Growing teams express the most uncertainty.',
                color: '#179eac',
                kind: 'analytics',
            },
            {
                product: 'Product analytics',
                value: '71% visited',
                detail: 'Most detractors saw the new pricing page.',
                color: '#2f80fa',
                kind: 'analytics',
            },
            {
                product: 'Session replay',
                value: '3 comparisons',
                detail: 'People revisit the usage table before leaving.',
                color: '#f0a512',
                kind: 'replay',
            },
        ],
        action: {
            primary: 'Draft a pricing update',
            status: '23 pricing responses',
            tone: 'info',
            confirmation: 'The pricing update draft is ready.',
            done: 'Pricing update drafted',
            followUp: {
                title: 'Did the pricing update clear things up?',
                summary:
                    'I’ll re-read new NPS responses once the pricing update is live and check whether detractors still mention the bill. If they do, I’ll bring their quotes back here.',
            },
        },
        completed: true,
        secondary: true,
    },
    {
        id: 'browser',
        title: 'Compare checkout by browser',
        meta: 'Product analytics · Yesterday',
        color: '#2f80fa',
        icon: 'analytics',
        heading: 'Safari accounts for the checkout gap.',
        paragraphs: [
            'Chrome and Firefox remain near their usual completion rates. Safari 17 falls sharply after payment submission.',
            'The browser comparison isolates the problem to one checkout path. Mobile Safari shows the largest drop.',
        ],
        evidence: [
            {
                product: 'Product analytics',
                value: '−13 points',
                detail: 'Safari trails the other browsers at checkout.',
                color: '#2f80fa',
                kind: 'analytics',
            },
            {
                product: 'Session replay',
                value: '38 sessions',
                detail: 'The same payment stall appears across sampled sessions.',
                color: '#0457ff',
                kind: 'replay',
            },
            {
                product: 'Error tracking',
                value: '1,284 events',
                detail: 'The error appears mainly in Safari 17.',
                color: '#e58e00',
                kind: 'error',
            },
            {
                product: 'Data warehouse',
                value: '3 browsers',
                detail: 'Chrome and Firefox stay near their baseline.',
                color: '#8567ff',
                kind: 'warehouse',
            },
        ],
        action: {
            primary: 'Merge PR #9123',
            status: 'PR ready · Safari trails by 13 points',
            tone: 'warning',
            confirmation: 'Merge requested for PR #9123.',
            done: 'Merged',
            pr: '#9123',
            followUp: {
                title: 'Did Safari catch up with Chrome?',
                summary:
                    'I’ll re-run the browser breakdown since PR #9123 merged and check that Safari is back near Chrome and Firefox at checkout.',
            },
        },
        secondary: true,
    },
    {
        id: 'guardrails',
        title: 'Review experiment guardrails',
        meta: 'Experiments · Yesterday',
        color: '#35b14e',
        icon: 'experiment',
        heading: 'The winning checkout passed every guardrail.',
        paragraphs: [
            'The shorter checkout increased completion without increasing refunds, support requests, or payment failures.',
            'Each guardrail stayed within its agreed range. The result is ready for a full rollout.',
        ],
        evidence: [
            {
                product: 'Experiments',
                value: '4 passed',
                detail: 'Every release guardrail stayed within range.',
                color: '#35b14e',
                kind: 'experiment',
            },
            {
                product: 'Product analytics',
                value: '+6.4%',
                detail: 'Checkout completion improved for the winning variant.',
                color: '#2f80fa',
                kind: 'analytics',
            },
            {
                product: 'Error tracking',
                value: 'No increase',
                detail: 'Payment and checkout errors stayed flat.',
                color: '#e58e00',
                kind: 'error',
            },
            {
                product: 'Surveys',
                value: 'Support flat',
                detail: 'The new flow did not increase support requests.',
                color: '#6d4fff',
                kind: 'survey',
            },
        ],
        action: {
            primary: 'Approve full rollout',
            status: '4 guardrails passed',
            tone: 'success',
            confirmation: 'The full rollout is approved.',
            icon: 'ship',
            done: 'Rolled out to 100%',
            run: {
                loading: 'Rolling out…',
                steps: ['Rolling out to 50%…', 'Guardrails holding. Rolling out to everyone…'],
                result: 'Rolled out. Refunds, support requests and payment errors are all within range.',
                live: 'Live for 100% of users',
            },
            followUp: {
                title: 'Did the guardrails hold after rollout?',
                summary:
                    'I’ll re-check refunds, support requests and payment errors with the new checkout at 100%. If any guardrail drifts out of range, I’ll bring it back here.',
            },
        },
        secondary: true,
    },
    {
        id: 'traces',
        title: 'Check summary-model traces',
        meta: 'LLM analytics · Yesterday',
        color: '#a737d2',
        icon: 'trace',
        heading: 'The new summary model repeats the source document.',
        paragraphs: [
            'Recent traces show the source text twice in the prompt. This duplication explains most of the token increase.',
            'The model change did not improve the quality score. The previous model remains the lower-cost option.',
        ],
        evidence: [
            {
                product: 'Tracing',
                value: '24 traces',
                detail: 'Each sampled trace contains the source text twice.',
                color: '#06b6d4',
                kind: 'trace',
            },
            {
                product: 'LLM analytics',
                value: '2.4× tokens',
                detail: 'Input tokens rose after the model change.',
                color: '#a737d2',
                kind: 'trace',
            },
            {
                product: 'Product analytics',
                value: 'Usage flat',
                detail: 'Traffic did not cause the higher cost.',
                color: '#2f80fa',
                kind: 'analytics',
            },
            {
                product: 'Data warehouse',
                value: 'Quality flat',
                detail: 'The quality score did not improve.',
                color: '#8567ff',
                kind: 'warehouse',
            },
        ],
        action: {
            primary: 'Merge prompt fix PR #9147',
            status: 'PR ready · 24 traces checked',
            tone: 'success',
            confirmation: 'Merge requested for PR #9147.',
            done: 'Merged',
            pr: '#9147',
            followUp: {
                title: 'Did the duplicate source text go away?',
                summary:
                    'I’ll sample new summarize-doc traces since PR #9147 merged and confirm the source document appears once. Input tokens should fall by about half.',
            },
        },
        secondary: true,
    },
]

/** The sample briefing, one array of segments per paragraph. */
export const SAMPLE_BRIEFING: TodayBriefingSegment[][] = [
    [
        {
            link: 'safari',
            text: 'Safari users can’t pay',
        },
        {
            text: ' since Tuesday’s deploy, and ',
        },
        {
            link: 'pr',
            text: 'a fix is waiting',
            highlight: true,
        },
        {
            text: ' for your review.',
        },
    ],
    [
        {
            link: 'exp',
            text: 'One-page checkout won',
        },
        {
            text: ' its experiment, and signups beat the forecast by 18%.',
        },
    ],
    [
        {
            text: 'Keep an eye on ',
        },
        {
            link: 'error',
            text: 'one new error',
        },
        {
            text: ', LLM cost per user ',
        },
        {
            link: 'llm',
            text: 'up 31%',
        },
        {
            text: ', and ',
        },
        {
            link: 'nps',
            text: 'pricing that confuses people',
        },
        {
            text: '.',
        },
    ],
]

export const FOLLOW_UP_OPTIONS: TodayFollowUpOption[] = [
    {
        id: 'tomorrow',
        label: 'Tomorrow, 9:00 am',
        phrase: 'tomorrow at 9:00 am',
        chip: 'Tomorrow',
    },
    {
        id: 'three-days',
        label: 'In 3 days',
        phrase: 'in 3 days',
        chip: 'In 3 days',
    },
    {
        id: 'monday',
        label: 'Next Monday, 9:00 am',
        phrase: 'next Monday at 9:00 am',
        chip: 'Monday',
    },
    {
        id: 'responses',
        label: 'After 20 new responses',
        phrase: 'after 20 new responses',
        chip: 'After 20 responses',
    },
]

export const AGENT_OPTIONS: TodayAgentOption[] = [
    {
        id: 'mine',
        name: 'My agent',
        detail: 'Claude Code · your repo',
        sent: 'Sent to your agent.',
    },
    {
        id: 'posthog',
        name: 'PostHog AI',
        detail: 'Works inside this project',
        sent: 'Sent to PostHog AI.',
    },
]

export const DRILL_OPTIONS: Record<TodayEvidenceKind, [string, string]> = {
    analytics: ['Open metric breakdown', 'View affected people'],
    code: ['Open changed files', 'View test results'],
    error: ['Open stack trace', 'View affected users'],
    experiment: ['Open variant results', 'View guardrails'],
    flag: ['Open rollout history', 'View targeted users'],
    replay: ['Open recording sample', 'View matching sessions'],
    survey: ['Open response themes', 'View individual responses'],
    trace: ['Open trace sample', 'View prompt and response'],
    warehouse: ['Open query result', 'View source rows'],
}

export const SAMPLE_RECENT_ERRORS: TodayRecentError[] = [
    {
        name: 'TypeError · formatAddress',
        detail: 'address.ts:42',
        count: '1,284',
        time: '2h',
    },
    {
        name: 'BillingAddressMissing',
        detail: 'payment.ts:118',
        count: '412',
        time: '2h',
    },
    {
        name: 'PaymentSubmitTimeout',
        detail: 'checkout.ts:76',
        count: '96',
        time: '1h',
    },
]

export const SAMPLE_RECORDINGS: TodayRecording[] = [
    {
        title: 'Payment stalls',
        detail: 'Safari 17 · London',
        duration: '00:42',
        step: 'Submit payment',
        note: 'No response after click',
    },
    {
        title: 'Submit clicked twice',
        detail: 'Safari 17 · Bristol',
        duration: '01:08',
        step: 'Confirm order',
        note: 'Button remains active',
    },
    {
        title: 'Checkout recovers',
        detail: 'Safari 16 · Leeds',
        duration: '00:51',
        step: 'Payment accepted',
        note: 'Redirect completes',
    },
]

export const SCENARIOS: Record<TodayScenarioId, TodayScenario> = {
    growth: {
        id: 'growth',
        suggestion: 'How do we grow 2×?',
        signal: 'Activation 37% · NPS 32',
        prompt: 'How do we grow 2×?',
        conclusion: 'Three changes could get us to 2×.',
        thinking: [
            'Reading 14,208 new team signups',
            'Comparing 8 weeks of retention cohorts',
            'Scanning 23 NPS responses about pricing',
            'Matching 16 lost upgrades to revenue',
        ],
        target: {
            label: 'Path to 2×',
            goal: 2,
        },
        evidence: [
            {
                id: 'onboarding-dropoff',
                eyebrow: 'Activation funnel',
                title: 'Onboarding has a drop-off.',
                summary: '41% of new teams leave when they reach the invite step.',
                source: 'Product analytics · 14,208 new teams',
                color: '#ff5c1c',
                readyAfter: 0,
                steps: [
                    {
                        label: 'Created a workspace',
                        value: '14,208',
                        width: 100,
                    },
                    {
                        label: 'Connected a source',
                        value: '9,642',
                        width: 68,
                    },
                    {
                        label: 'Invited a teammate',
                        value: '5,688',
                        width: 40,
                    },
                    {
                        label: 'Reached first insight',
                        value: '4,972',
                        width: 35,
                    },
                ],
                recommendation:
                    'Move the invite step after the first insight. Let one person reach value before you ask them to recruit a teammate.',
                action: 'Merge invite-step PR',
                done: 'Merged',
                lever: 'Move the invite step',
                impact: 0.35,
            },
            {
                id: 'activation-gap',
                eyebrow: 'Retention cohorts',
                title: 'Too few teams reach the value moment.',
                summary: 'Teams that create one insight retain 2.4× better after four weeks.',
                source: 'Cohorts · 8 weeks of retention',
                color: '#2f80fa',
                readyAfter: 3200,
                steps: [
                    {
                        label: 'No insight created',
                        value: '18% retained',
                        width: 32,
                    },
                    {
                        label: 'One insight created',
                        value: '43% retained',
                        width: 74,
                    },
                    {
                        label: 'Three insights created',
                        value: '58% retained',
                        width: 100,
                    },
                ],
                recommendation:
                    'Guide each new team to one useful insight during its first session. Make that the main activation goal.',
                action: 'Merge first-insight guide',
                done: 'Merged',
                lever: 'Reach a first insight sooner',
                impact: 0.45,
            },
            {
                id: 'pricing-friction',
                eyebrow: 'Surveys + revenue',
                title: 'Pricing is slowing expansion.',
                summary: 'Pricing confusion appears in 23 NPS responses and 16 lost upgrades.',
                source: 'Surveys · Revenue analytics',
                color: '#7c5cff',
                readyAfter: 5100,
                steps: [
                    {
                        label: 'Viewed pricing',
                        value: '1,284',
                        width: 100,
                    },
                    {
                        label: 'Started upgrade',
                        value: '406',
                        width: 53,
                    },
                    {
                        label: 'Completed upgrade',
                        value: '231',
                        width: 31,
                    },
                ],
                recommendation:
                    'Show the expected bill before checkout. Explain the usage estimate beside the total instead of in a separate tooltip.',
                action: 'Publish pricing draft',
                done: 'Published',
                lever: 'Show the bill up front',
                impact: 0.25,
            },
        ],
    },
    checkout: {
        id: 'checkout',
        suggestion: 'Recover Safari checkout conversion',
        signal: '−12 points since Tuesday',
        prompt: 'Why are Safari users abandoning checkout?',
        conclusion: 'Here’s how I think we can recover Safari checkout conversion.',
        thinking: ['Reading 1,284 checkout errors', 'Watching 38 Safari recordings', 'Comparing completion by browser'],
        evidence: [
            {
                id: 'safari-error',
                eyebrow: 'Error tracking',
                title: 'The billing address fails on Safari.',
                summary: 'A new TypeError blocks payment submission for Safari 17 users.',
                source: 'Error tracking · 1,284 events',
                color: '#e58e00',
                readyAfter: 0,
                steps: [
                    {
                        label: 'Reached checkout',
                        value: '6,410',
                        width: 100,
                    },
                    {
                        label: 'Submitted payment',
                        value: '4,172',
                        width: 65,
                    },
                    {
                        label: 'Safari completed',
                        value: '1,038',
                        width: 34,
                    },
                ],
                recommendation:
                    'Ship PR #9123, then watch Safari completion for one hour. Roll back if errors do not fall.',
                action: 'Merge PR #9123',
                done: 'Merged',
            },
            {
                id: 'safari-replays',
                eyebrow: 'Session replay',
                title: 'The failure looks silent to customers.',
                summary: '38 recordings stop after the payment button without an error message.',
                source: 'Session replay · Safari 17',
                color: '#0457ff',
                readyAfter: 2800,
                steps: [
                    {
                        label: 'Clicked payment',
                        value: '38 sessions',
                        width: 100,
                    },
                    {
                        label: 'Saw an error',
                        value: '2 sessions',
                        width: 18,
                    },
                ],
                recommendation:
                    'Add an inline payment error that preserves the form values. Customers need a clear recovery action.',
                action: 'Merge inline-error PR',
                done: 'Merged',
            },
            {
                id: 'browser-baseline',
                eyebrow: 'Product analytics',
                title: 'Chrome conversion stayed flat.',
                summary: 'The change is isolated to Safari rather than the new checkout design.',
                source: 'Browser breakdown · 7 days',
                color: '#35b14e',
                readyAfter: 4600,
                steps: [
                    {
                        label: 'Chrome',
                        value: '64% complete',
                        width: 100,
                    },
                    {
                        label: 'Firefox',
                        value: '61% complete',
                        width: 95,
                    },
                    {
                        label: 'Safari',
                        value: '49% complete',
                        width: 76,
                    },
                ],
                recommendation:
                    'Keep the experiment running for other browsers. Limit the emergency change to Safari payment handling.',
                action: 'Turn on Safari-only flag',
                done: 'Flag on',
            },
        ],
    },
    'llm-cost': {
        id: 'llm-cost',
        suggestion: 'Bring LLM cost per user back down',
        signal: '+31% this week',
        prompt: 'What caused LLM cost per user to rise 31%?',
        conclusion: 'Here’s how I think we can bring LLM cost per user back down.',
        thinking: [
            'Reading 84,102 generations',
            'Diffing summarize-doc prompt versions',
            'Counting retries by document type',
        ],
        evidence: [
            {
                id: 'model-change',
                eyebrow: 'AI observability',
                title: 'summarize-doc changed models.',
                summary: 'Most new cost comes from a larger model on routine summaries.',
                source: 'Traces · 84,102 generations',
                color: '#a737d2',
                readyAfter: 0,
                steps: [
                    {
                        label: 'Previous model',
                        value: '$0.021 / run',
                        width: 44,
                    },
                    {
                        label: 'Current model',
                        value: '$0.048 / run',
                        width: 100,
                    },
                ],
                recommendation:
                    'Route short documents to the previous model. Keep the larger model for long or low-confidence summaries.',
                action: 'Merge model-routing PR',
                done: 'Merged',
            },
            {
                id: 'prompt-growth',
                eyebrow: 'Prompt analytics',
                title: 'The system prompt grew by 62%.',
                summary: 'Repeated examples now account for 18% of input tokens.',
                source: 'Prompts · summarize-doc v18',
                color: '#ef3f8e',
                readyAfter: 2900,
                steps: [
                    {
                        label: 'Instructions',
                        value: '2,406 tokens',
                        width: 63,
                    },
                    {
                        label: 'Examples',
                        value: '1,146 tokens',
                        width: 31,
                    },
                    {
                        label: 'Document',
                        value: '3,822 tokens',
                        width: 100,
                    },
                ],
                recommendation:
                    'Keep two representative examples. Retrieve rare examples only when the document type needs them.',
                action: 'Merge trimmed prompt',
                done: 'Merged',
            },
            {
                id: 'retry-volume',
                eyebrow: 'LLM traces',
                title: 'Retries doubled for scanned PDFs.',
                summary: 'Low-quality extraction causes the agent to repeat the same request.',
                source: 'Tracing · 2,810 retries',
                color: '#08a9bd',
                readyAfter: 4800,
                steps: [
                    {
                        label: 'Digital documents',
                        value: '1.08 runs',
                        width: 48,
                    },
                    {
                        label: 'Scanned PDFs',
                        value: '2.24 runs',
                        width: 100,
                    },
                ],
                recommendation:
                    'Check extraction quality before generation. Send weak scans to OCR instead of retrying the summary.',
                action: 'Merge OCR fallback',
                done: 'Merged',
            },
        ],
    },
}

export const REMIND_OPTIONS: TodayMenuOption[] = [
    {
        id: '30m',
        label: 'In 30 min',
    },
    {
        id: '1h',
        label: 'In 1 hour',
    },
    {
        id: 'tomorrow',
        label: 'Tomorrow',
        detail: '9:00 am',
    },
]

export const SEND_OPTIONS: TodayMenuOption[] = [
    {
        id: 'linear',
        label: 'Linear',
        detail: 'Create an issue in Growth',
    },
    {
        id: 'jira',
        label: 'Jira',
        detail: 'Create a ticket in GROW',
    },
]
