import { experiment, flag, survey } from '@posthog/sdk/define'

export const newCheckout = flag('new-checkout', {
    name: 'New checkout flow',
    variants: ['control', 'test'],
    rollout: 100,
})

export const checkoutExperiment = experiment('new_checkout_experiment', {
    name: 'New checkout flow',
    description: 'Does the new checkout flow raise completed checkouts?',
    feature_flag_key: newCheckout,
})

export const checkoutSurvey = survey('checkout_feedback', {
    name: 'Checkout feedback',
    type: 'popover',
    linked_flag_id: newCheckout,
    questions: [{ type: 'open', question: 'How was checking out today?' }],
})
