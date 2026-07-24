import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Link } from 'lib/lemon-ui/Link'

import coffeeHog from 'public/hedgehog/coffee-hog.png'

import { HERTS_WILDLIFE_TRUST_DONATE_URL, buyHedgehogCoffeeLogic } from './buyHedgehogCoffeeLogic'

/** Self-gating wrapper, mounted in GlobalModals. Renders nothing unless the current user is a
 * long-term free-tier user who's stayed under their allowance, and only up to twice a year. */
export function MaybeBuyHedgehogCoffeeModal(): JSX.Element | null {
    const { shouldShowModal } = useValues(buyHedgehogCoffeeLogic)
    const { closeModal, donate } = useActions(buyHedgehogCoffeeLogic)
    if (!shouldShowModal) {
        return null
    }
    return <BuyHedgehogCoffeeModal isOpen onClose={closeModal} onDonate={donate} />
}

export interface BuyHedgehogCoffeeModalProps {
    isOpen: boolean
    onClose: () => void
    onDonate: () => void
    /** Render in place instead of in a portal — for Storybook. */
    inline?: boolean
}

export function BuyHedgehogCoffeeModal({
    isOpen,
    onClose,
    onDonate,
    inline,
}: BuyHedgehogCoffeeModalProps): JSX.Element {
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
                <img src={coffeeHog} alt="" className="w-40 mb-3" />
                <h2 className="text-2xl font-bold mb-2">Buy a hog a coffee</h2>
                <div className="flex flex-col gap-2 max-w-md text-secondary">
                    <p className="m-0">
                        Twice a year, we ask that if you've been enjoying PostHog for free then you consider passing it
                        on by donating to our favourite cause: hedgehog caffination.
                    </p>
                    <p className="m-0">
                        The{' '}
                        <Link to={HERTS_WILDLIFE_TRUST_DONATE_URL} target="_blank" disableClientSideRouting>
                            Herts &amp; Middlesex Wildlife Trust
                        </Link>{' '}
                        has benefitted from PostHog's support since the beginning. Even small donations can help them
                        restore natural habitats and protect local wildlife in the UK. If you'd rather donate to
                        another cause though then you can do that too!
                    </p>
                </div>
            </div>
        </LemonModal>
    )
}
