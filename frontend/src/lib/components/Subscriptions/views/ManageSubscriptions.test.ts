import { SubscriptionType, WeekdayType } from '~/types'
import { weekdayOptions } from '../utils'
import { summarizeSubscription } from './ManageSubscriptions'

const createSubscription = (props: Partial<SubscriptionType> = {}): SubscriptionType =>
    ({
        id: 1,
        title: 'My example subscription',
        target_type: 'email',
        target_value: 'ben@posthog.com,geoff@other-company.com',
        frequency: 'monthly',
        start_date: '2022-01-01T00:09:00',
        interval: 1,
        // byweekday: ['wednesday'],
        // bysetpos: 1,
        ...props,
    } as SubscriptionType)

describe('summarizeSubscription', () => {
    it('it generates a relevant subscription', () => {
        let subscription = createSubscription()
        expect(summarizeSubscription(subscription)).toEqual('Sent every month')
        subscription = createSubscription({ interval: 2, byweekday: ['wednesday'], bysetpos: 1 })
        expect(summarizeSubscription(subscription)).toEqual('Sent every 2 months on the first wednesday')
        subscription = createSubscription({ interval: 1, frequency: 'weekly', byweekday: ['wednesday'], bysetpos: -1 })
        expect(summarizeSubscription(subscription)).toEqual('Sent every week on the last wednesday')
        subscription = createSubscription({ interval: 1, frequency: 'weekly', byweekday: ['wednesday'] })
        expect(summarizeSubscription(subscription)).toEqual('Sent every week')
        subscription = createSubscription({
            interval: 1,
            frequency: 'monthly',
            byweekday: Object.keys(weekdayOptions) as WeekdayType[],
            bysetpos: 3,
        })
        expect(summarizeSubscription(subscription)).toEqual('Sent every month on the third day')
    })
})
