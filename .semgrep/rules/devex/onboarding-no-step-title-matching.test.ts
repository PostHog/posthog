// @ts-nocheck
// Test fixture for the onboarding-no-step-title-matching rule.
// Flagged: selecting a step by its display title, however the comparison is written.
// Accepted: declaring a title, or comparing something that is not a title.

// ruleid: onboarding-no-step-title-matching
const a = paSteps.filter((step) => step.title !== 'Send events')

// ruleid: onboarding-no-step-title-matching
const b = paSteps.filter((step) => step.title === 'Send events')

// loose comparison
// ruleid: onboarding-no-step-title-matching
const c = paSteps.filter((step) => step.title != 'Send events')

// ruleid: onboarding-no-step-title-matching
const d = paSteps.filter((step) => step.title == 'Send events')

// destructured parameter
// ruleid: onboarding-no-step-title-matching
const e = paSteps.filter(({ title }) => title !== 'Send events')

// reversed operands
// ruleid: onboarding-no-step-title-matching
const f = paSteps.filter((step) => 'Send events' !== step.title)

// ruleid: onboarding-no-step-title-matching
const g = paSteps.find((step) => 'Send events' === step.title)

// bracket access
// ruleid: onboarding-no-step-title-matching
const h = paSteps.filter((step) => step['title'] === 'Send events')

// double quotes, any receiver name
// ruleid: onboarding-no-step-title-matching
const i = paSteps.map((s) => (s.title === "Send events" ? replacement : s))

// template literal
// ruleid: onboarding-no-step-title-matching
const j = paSteps.filter((step) => step.title !== `Send events`)

// ok: onboarding-no-step-title-matching
const k = [...getReactInstallSteps(ctx), { title: 'Send events', badge: 'recommended', content: null }]

// ok: onboarding-no-step-title-matching
const l = paSteps.filter((step) => step.badge === 'recommended')

// ok: onboarding-no-step-title-matching
const m = { title: 'Send events' }

// ok: onboarding-no-step-title-matching
const n = paSteps.filter((step) => step.title.length === 0)
