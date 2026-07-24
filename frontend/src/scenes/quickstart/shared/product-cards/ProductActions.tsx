import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { InstallationProgress } from 'scenes/onboarding/shared/wizard-sync/installationProgressLogic'
import { wizardSyncUiLogic } from 'scenes/onboarding/shared/wizard-sync/wizardSyncUiLogic'

import { QuickstartProduct, quickstartLogic } from '../../quickstartLogic'
import { captureQuickstartAction } from '../captureQuickstartAction'
import { PRODUCT_SDK_SETUP } from '../productSdkSetup'
import { isQuickstartProductInstalling } from '../QuickstartWizardProgress'

export function ProductActions({
    product,
    compact = false,
    installationProgress,
}: {
    product: QuickstartProduct
    compact?: boolean
    installationProgress?: InstallationProgress
}): JSX.Element {
    const { enablingProducts } = useValues(quickstartLogic)
    const { enableProduct, openToolSetupModal } = useActions(quickstartLogic)
    const { openDialog } = useActions(wizardSyncUiLogic)
    const { status } = product
    const installationInProgress = isQuickstartProductInstalling(product.key, installationProgress)

    const setUpButton = (
        <LemonButton
            type={compact ? 'secondary' : 'primary'}
            size="small"
            to={PRODUCT_SDK_SETUP[product.key] ? undefined : product.setupUrl}
            onClick={() => {
                captureQuickstartAction('set_up_product', product.key)
                if (PRODUCT_SDK_SETUP[product.key]) {
                    openToolSetupModal(product.key)
                }
            }}
            data-attr={`quickstart-setup-${product.key}`}
        >
            {status.cta === 'install' ? 'Install' : 'Set up'}
        </LemonButton>
    )
    const enableButton = (type: 'primary' | 'secondary'): JSX.Element => (
        <LemonButton
            type={type}
            size="small"
            loading={!!enablingProducts[product.key]}
            onClick={() => {
                captureQuickstartAction('enable_product', product.key)
                enableProduct(product.key)
            }}
            data-attr={`quickstart-enable-${product.key}`}
        >
            Enable
        </LemonButton>
    )
    const openButton = (
        <LemonButton
            type={compact ? 'secondary' : 'primary'}
            size="small"
            to={product.url}
            onClick={() => captureQuickstartAction('open_product', product.key)}
            data-attr={`quickstart-open-${product.key}`}
        >
            Open
        </LemonButton>
    )
    const installingButton = (
        <LemonButton
            type={compact ? 'secondary' : 'primary'}
            size="small"
            icon={<span className="inline-block size-2 rounded-full bg-accent animate-pulse" />}
            onClick={openDialog}
            data-attr={`quickstart-installing-${product.key}`}
        >
            Installing SDK
        </LemonButton>
    )

    if (compact) {
        return installationInProgress
            ? installingButton
            : status.level === 'live'
              ? openButton
              : status.cta === 'enable'
                ? enableButton('secondary')
                : status.cta === 'open'
                  ? openButton
                  : setUpButton
    }

    return (
        <div className="flex items-center gap-2 mt-1">
            {installationInProgress ? (
                installingButton
            ) : status.level === 'live' ? (
                <>
                    {openButton}
                    {/* e.g. error tracking live from a server SDK can still turn on web autocapture */}
                    {status.cta === 'enable' && enableButton('secondary')}
                </>
            ) : status.cta === 'enable' ? (
                enableButton('primary')
            ) : status.cta === 'open' ? (
                <>
                    {openButton}
                    {PRODUCT_SDK_SETUP[product.key] && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => {
                                captureQuickstartAction('open_sdk_guide', product.key)
                                openToolSetupModal(product.key)
                            }}
                            data-attr={`quickstart-sdk-guide-${product.key}`}
                        >
                            SDK guide
                        </LemonButton>
                    )}
                </>
            ) : (
                setUpButton
            )}
            {product.docsUrl && (
                <LemonButton
                    size="small"
                    to={product.docsUrl}
                    targetBlank
                    onClick={() => captureQuickstartAction('open_docs', product.key)}
                    data-attr={`quickstart-docs-${product.key}`}
                >
                    Docs
                </LemonButton>
            )}
        </div>
    )
}
