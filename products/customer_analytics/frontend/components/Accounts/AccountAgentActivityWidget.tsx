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
        <div className="flex flex-col gap-2">
            <AccountWidgetWeeksSelect weeks={weeks} onChange={setWeeks} />
            {loadFailed ? (
                <LemonBanner type="warning" action={{ children: 'Try again', onClick: () => loadResult() }}>
                    {result
                        ? "Couldn't refresh agent activity. These numbers are from the last range that loaded."
                        : "Couldn't load agent activity for this account."}
                </LemonBanner>
            ) : null}
            {result ? (
                <AccountAgentActivity result={result} loading={resultLoading} />
            ) : loadFailed ? null : (
                <LemonSkeleton className="h-64 w-full" />
            )}
        </div>
    )
}
