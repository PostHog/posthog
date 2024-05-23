import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonModal, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { confirmUpgradeModalLogic } from './confirmUpgradeModalLogic'

export function ConfirmUpgradeModal(): JSX.Element {
    const { upgradePlan } = useValues(confirmUpgradeModalLogic)
    const { hideConfirmUpgradeModal, confirm, cancel } = useActions(confirmUpgradeModalLogic)

    return (
        <LemonModal
            onClose={hideConfirmUpgradeModal}
            isOpen={!!upgradePlan}
            title={`Ready to subscribe to the ${upgradePlan?.name}?`}
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => cancel()}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={() => confirm()}>
                        Sign me up
                    </LemonButton>
                </>
            }
        >
            <div className="max-w-120">
                <p>
                    Woo! You're gonna love the {upgradePlan?.name}. We're just confirming that this is a $
                    {Number(upgradePlan?.unit_amount_usd)}/{upgradePlan?.unit} subscription and the first payment will
                    be charged immediately.
                </p>
                {upgradePlan && upgradePlan?.features?.length > 1 && (
                    <div>
                        <p className="ml-0 mb-2 max-w-200">Here are the features included:</p>
                        {upgradePlan?.features.map((feature, i) => {
                            return (
                                i < 6 && (
                                    <div className="flex gap-x-2 items-center mb-2" key={'addon-features-' + i}>
                                        <IconCheckCircle className="text-success" />
                                        <Tooltip key={feature.key} title={feature.description}>
                                            <b>{feature.name} </b>
                                        </Tooltip>
                                    </div>
                                )
                            )
                        })}
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
