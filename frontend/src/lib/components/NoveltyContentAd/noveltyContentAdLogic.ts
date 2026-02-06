import { actions, afterMount, kea, path, reducers, selectors } from 'kea'

import type { noveltyContentAdLogicType } from './noveltyContentAdLogicType'

export interface FictionalAd {
    title: string
    description: string
    price: string
    cta: string
}

const FICTIONAL_ADS: FictionalAd[] = [
    {
        title: "Tom Jones' Catalan Cookbook",
        description: "Pre-order the legendary Welsh singer's guide to Catalonian cuisine",
        price: '$0.00',
        cta: 'Pre-order now',
    },
    {
        title: 'Self-Folding Laundry',
        description: 'Finally, laundry that folds itself using patented quantum fabric technology',
        price: 'Free with Prime',
        cta: 'Add to cart',
    },
    {
        title: 'Invisible Sunglasses',
        description: 'Block 100% of UV rays without blocking your style',
        price: '$299.99',
        cta: 'Shop now',
    },
    {
        title: 'Procrastination Pills',
        description: "Do it tomorrow with today's most effective procrastination supplement",
        price: '$19.99/mo',
        cta: 'Subscribe',
    },
    {
        title: 'Left-Handed Screwdrivers',
        description: 'Finally, screwdrivers designed for left-handed people',
        price: '$49.99',
        cta: 'Buy now',
    },
    {
        title: 'Dream Recorder Pro',
        description: 'Record and replay your dreams in 4K HDR with Dolby Atmos',
        price: '$499.00',
        cta: 'Learn more',
    },
    {
        title: 'Anti-Gravity Shoes',
        description: 'Walk on the ceiling with our patented anti-gravity technology',
        price: '$1,299.99',
        cta: 'Try them on',
    },
    {
        title: 'Bluetooth-Enabled Rocks',
        description: 'Connect your rocks to the IoT ecosystem',
        price: '$89.99',
        cta: 'Get yours',
    },
    {
        title: 'Time Machine Lite',
        description: 'Travel up to 15 minutes into the past (future travel sold separately)',
        price: '$9,999.99',
        cta: 'Pre-order',
    },
    {
        title: 'Organic Free-Range Pixels',
        description: 'Ethically sourced pixels for your next design project',
        price: '$0.99/pixel',
        cta: 'Shop pixels',
    },
    {
        title: 'Silent Alarm Clock',
        description: 'Wake up without any sound, light, or vibration',
        price: '$79.99',
        cta: 'Buy now',
    },
    {
        title: 'Dehydrated Water',
        description: 'Just add water! Perfect for camping and emergencies',
        price: '$5.99',
        cta: 'Add to cart',
    },
]

export const noveltyContentAdLogic = kea<noveltyContentAdLogicType>([
    path(['lib', 'components', 'NoveltyContentAd', 'noveltyContentAdLogic']),

    actions({
        setCurrentAdIndex: (index: number) => ({ index }),
        showNextAd: true,
        dismissAd: true,
        undoDismiss: true,
    }),

    reducers({
        currentAdIndex: [
            0 as number,
            {
                setCurrentAdIndex: (_, { index }) => index,
                showNextAd: (state) => (state + 1) % FICTIONAL_ADS.length,
            },
        ],
        isDismissed: [
            false,
            {
                dismissAd: () => true,
                undoDismiss: () => false,
            },
        ],
    }),

    selectors({
        currentAd: [(s) => [s.currentAdIndex], (currentAdIndex): FictionalAd => FICTIONAL_ADS[currentAdIndex]],
        allAds: [() => [], (): FictionalAd[] => FICTIONAL_ADS],
    }),

    afterMount(({ actions, cache }) => {
        // Pick a random ad to start with
        const randomIndex = Math.floor(Math.random() * FICTIONAL_ADS.length)
        actions.setCurrentAdIndex(randomIndex)

        // Rotate ads every 30 seconds
        cache.interval = setInterval(() => {
            actions.showNextAd()
        }, 30000)

        return () => {
            if (cache.interval) {
                clearInterval(cache.interval)
            }
        }
    }),
])
