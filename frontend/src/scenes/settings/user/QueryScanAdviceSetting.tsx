import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { uiCustomizationLogic } from '~/layout/uiCustomizationLogic'

export function QueryScanAdviceSetting(): JSX.Element {
    const { showQueryScanAdvice } = useValues(uiCustomizationLogic)
    const { setQueryScanAdviceShown } = useActions(uiCustomizationLogic)
    const { userLoading } = useValues(userLogic)

    return (
        <LemonSwitch
            onChange={(checked) => setQueryScanAdviceShown(checked)}
            checked={showQueryScanAdvice}
            loading={userLoading}
            label="Show advice on slow queries"
            bordered
        />
    )
}
