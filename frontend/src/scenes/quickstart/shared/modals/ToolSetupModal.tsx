import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { quickstartLogic } from '../../quickstartLogic'
import { captureQuickstartAction } from '../captureQuickstartAction'
import { ToolSetupModalContent } from './ToolSetupModalContent'

export function ToolSetupModal({ installationComplete }: { installationComplete: boolean }): JSX.Element {
    const { setupModalProduct } = useValues(quickstartLogic)
    const { closeToolSetupModal } = useActions(quickstartLogic)

    return (
        <LemonModal
            isOpen={!!setupModalProduct}
            onClose={closeToolSetupModal}
            title={setupModalProduct ? `Set up ${setupModalProduct.name}` : ''}
            width="52rem"
            footer={
                setupModalProduct && (
                    <div className="flex items-center justify-end gap-2">
                        {setupModalProduct.docsUrl && (
                            <LemonButton
                                to={setupModalProduct.docsUrl}
                                targetBlank
                                onClick={() => captureQuickstartAction('open_docs', setupModalProduct.key)}
                                data-attr="quickstart-setup-modal-docs"
                            >
                                Docs
                            </LemonButton>
                        )}
                        <LemonButton
                            type="primary"
                            to={setupModalProduct.setupUrl}
                            onClick={() => {
                                captureQuickstartAction('open_setup_guide', setupModalProduct.key)
                                closeToolSetupModal()
                            }}
                            data-attr="quickstart-setup-modal-guide"
                        >
                            Open full setup guide
                        </LemonButton>
                    </div>
                )
            }
        >
            {setupModalProduct && (
                <ToolSetupModalContent product={setupModalProduct} installationComplete={installationComplete} />
            )}
        </LemonModal>
    )
}
