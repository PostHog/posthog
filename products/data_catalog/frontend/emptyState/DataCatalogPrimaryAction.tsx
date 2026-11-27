import { useActions, useValues } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { catalogSetupLogic } from '../catalogSetupLogic'
import { CopyAgentSetupPromptButton } from '../components/CopyAgentSetupPromptButton'
import { SetupWithPostHogAIButton } from '../components/SetupWithPostHogAIButton'

export function DataCatalogPrimaryAction({ preview }: { preview: boolean }): JSX.Element {
    const { postHogAISetupAvailable } = useValues(catalogSetupLogic)
    const { reportSetupEmptyStateShown } = useActions(catalogSetupLogic)

    useOnMountEffect(() => {
        if (!preview) {
            reportSetupEmptyStateShown()
        }
    })

    const defineFirstMetric = (
        <LemonButton
            type={postHogAISetupAvailable ? 'secondary' : 'primary'}
            to={urls.dataCatalogNewMetric()}
            data-attr="data-catalog-new-metric-button"
        >
            Define your first metric
        </LemonButton>
    )

    return (
        <div className="flex flex-wrap items-center gap-2">
            {postHogAISetupAvailable ? (
                <>
                    <SetupWithPostHogAIButton source="empty_state" />
                    {defineFirstMetric}
                    <CopyAgentSetupPromptButton source="empty_state" type="tertiary" />
                </>
            ) : (
                <>
                    {defineFirstMetric}
                    <CopyAgentSetupPromptButton source="empty_state" />
                </>
            )}
        </div>
    )
}
