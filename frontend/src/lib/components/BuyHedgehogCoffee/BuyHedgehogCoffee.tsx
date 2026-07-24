import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Link } from 'lib/lemon-ui/Link'

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
            title="Buy a hedgehog a coffee ☕️🦔"
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
                        Donate to Herts Wildlife Trust
                    </LemonButton>
                </div>
            }
        >
            <div className="flex flex-col gap-2 max-w-md">
                <p className="m-0">
                    You've been happily under the free allowance for a while now and we're fine with that, but...
                </p>
                <p className="m-0">
                    If you've enjoyed using PostHog, we'd like you to consider passing it on by donating to our
                    favourite cause: Hedgehogs. A small donation to the{' '}
                    <Link to={HERTS_WILDLIFE_TRUST_DONATE_URL} target="_blank" disableClientSideRouting>
                        Herts Wildlife Trust
                    </Link>{' '}
                    helps look after hedgehogs and the wild places they live. No pressure — this only pops up twice a
                    year.
                </p>
            </div>
        </LemonModal>
    )
}
