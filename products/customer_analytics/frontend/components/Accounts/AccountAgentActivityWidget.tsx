import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { AccountAgentActivity } from './AccountAgentActivity'
import { accountAgentActivityLogic, type AccountAgentActivityLogicProps } from './accountAgentActivityLogic'
import { AccountWidgetWeeksSelect } from './AccountWidgetWeeksSelect'

export function AccountAgentActivityWidget(props: AccountAgentActivityLogicProps): JSX.Element {
    const logic = accountAgentActivityLogic(props)
    const { result, resultLoading, loadFailed, weeks } = useValues(logic)
    const { setWeeks, loadResult } = useActions(logic)

    return (
        <>
            <AccountWidgetWeeksSelect weeks={weeks} onChange={setWeeks} />
            {result ? (
                <AccountAgentActivity result={result} loading={resultLoading} />
            ) : loadFailed ? (
                <LemonBanner type="warning" action={{ children: 'Try again', onClick: () => loadResult() }}>
                    Couldn't load agent activity for this account.
                </LemonBanner>
            ) : (
                <LemonSkeleton className="h-64 w-full" />
            )}
        </>
    )
}
