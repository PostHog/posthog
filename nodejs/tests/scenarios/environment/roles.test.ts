import { INTAKE_TRANSACTIONAL_EMAIL_GROUP, SES_WEBHOOKS_GROUP, drainedGroupsOf } from './roles'

describe('the consumer groups a run drains before it converges', () => {
    const groups = [
        { group: 'cdp-processed-events-consumer', topics: ['events'] },
        { group: INTAKE_TRANSACTIONAL_EMAIL_GROUP, topics: ['intake'] },
        { group: SES_WEBHOOKS_GROUP, topics: ['ses'] },
    ]

    it.each<[string, boolean, string[]]>([
        ['posts SES feedback', true, [INTAKE_TRANSACTIONAL_EMAIL_GROUP, SES_WEBHOOKS_GROUP]],
        ['posts no SES feedback', false, [INTAKE_TRANSACTIONAL_EMAIL_GROUP]],
    ])('drains the intake groups, and the SES webhook group when the profile %s', (_story, feedback, drained) => {
        expect(drainedGroupsOf(groups, feedback).map(({ group }) => group)).toEqual(drained)
    })
})
