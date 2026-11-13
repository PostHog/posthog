import { useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { urls } from 'scenes/urls'

import { CopyAgentSetupPromptButton } from '../components/CopyAgentSetupPromptButton'
import { SetupWithPostHogAIButton } from '../components/SetupWithPostHogAIButton'

export function DataCatalogPrimaryAction(): JSX.Element {
    const { isMaxAvailable } = useValues(maxGlobalLogic)

    const defineFirstMetric = (
        <LemonButton
            type={isMaxAvailable ? 'secondary' : 'primary'}
            to={urls.dataCatalogNewMetric()}
            data-attr="data-catalog-new-metric-button"
        >
            Define your first metric
        </LemonButton>
    )

    return (
        <div className="flex flex-wrap items-center gap-2">
            {isMaxAvailable ? (
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
