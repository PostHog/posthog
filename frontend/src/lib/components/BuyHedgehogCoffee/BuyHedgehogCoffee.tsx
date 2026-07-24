import { useActions, useValues } from 'kea'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Link } from 'lib/lemon-ui/Link'

import coffeeHog from 'public/hedgehog/coffee-hog.png'
import moneyHog from 'public/hedgehog/money-hog.png'

import {
    HERTS_WILDLIFE_TRUST_DONATE_URL,
    HedgehogDonationVariant,
    buyHedgehogCoffeeLogic,
    donationVariantForDate,
} from './buyHedgehogCoffeeLogic'

function TrustLink(): JSX.Element {
    return (
        <Link to={HERTS_WILDLIFE_TRUST_DONATE_URL} target="_blank" disableClientSideRouting>
            Herts &amp; Middlesex Wildlife Trust
        </Link>
    )
}

const VARIANT_CONTENT: Record<HedgehogDonationVariant, { image: string; title: string; body: JSX.Element }> = {
    coffee: {
        image: coffeeHog,
        title: 'Buy a hog a coffee',
        body: (
            <>
                <p className="m-0">
                    Twice a year, we ask that if you've been enjoying PostHog for free then pass it on by donating to
                    our favourite cause: hedgehogs.
                </p>
                <p className="m-0">
                    The <TrustLink /> has benefitted from PostHog's support since we started. Even small donations help
                    them restore natural habitats and protect local wildlife in the UK. If you'd rather donate to
                    another cause though then you can do that too!
                </p>
            </>
        ),
    },
    money: {
        image: moneyHog,
        title: "We've got plenty of money",
        body: (
            <>
                <p className="m-0">
                    You've been using PostHog for free, which is great. We don't need the money, but we know who does.
                </p>
                <p className="m-0">
                    The <TrustLink /> has benefitted from PostHog's support since we started. Twice a year, we ask that
                    if you've enjoyed using PostHog for free then you consider supporting their cause. Or, you can
                    donate elsewhere if you prefer!
                </p>
            </>
        ),
    },
}

/** Self-gating wrapper, mounted in GlobalModals. Renders nothing unless the current user is a
 * long-term free-tier user who's stayed under their allowance, and only up to twice a year. */
export function MaybeBuyHedgehogCoffeeModal(): JSX.Element | null {
    const { shouldShowModal } = useValues(buyHedgehogCoffeeLogic)
    const { closeModal, donate } = useActions(buyHedgehogCoffeeLogic)
    if (!shouldShowModal) {
        return null
    }
    return (
        <BuyHedgehogCoffeeModal isOpen onClose={closeModal} onDonate={donate} variant={donationVariantForDate(dayjs())} />
    )
}

export interface BuyHedgehogCoffeeModalProps {
    isOpen: boolean
    onClose: () => void
    onDonate: () => void
    variant?: HedgehogDonationVariant
    /** Render in place instead of in a portal — for Storybook. */
    inline?: boolean
}

export function BuyHedgehogCoffeeModal({
    isOpen,
    onClose,
    onDonate,
    variant = 'coffee',
    inline,
}: BuyHedgehogCoffeeModalProps): JSX.Element {
    const content = VARIANT_CONTENT[variant]
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            inline={inline}
            width={480}
            data-attr="buy-hedgehog-coffee"
            footer={
                <div className="flex flex-row justify-between items-center w-full">
                    <LemonButton type="tertiary" onClick={onClose} data-attr="hedgehog-coffee-dismiss">
                        Maybe later
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        to={HERTS_WILDLIFE_TRUST_DONATE_URL}
                        targetBlank
                        disableClientSideRouting
                        onClick={onDonate}
                        data-attr="hedgehog-coffee-donate"
                    >
                        Donate
                    </LemonButton>
                </div>
            }
        >
            <div className="flex flex-col items-center text-center pt-2 pb-1">
                <img src={content.image} alt="" className="w-40 mb-3" />
                <h2 className="text-2xl font-bold mb-2">{content.title}</h2>
                <div className="flex flex-col gap-2 max-w-md text-secondary">{content.body}</div>
            </div>
        </LemonModal>
    )
}
