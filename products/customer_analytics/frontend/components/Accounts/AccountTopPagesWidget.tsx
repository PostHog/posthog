import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { AccountTopPages } from './AccountTopPages'
import { accountTopPagesLogic, type AccountTopPagesLogicProps } from './accountTopPagesLogic'
import { AccountWidgetWeeksSelect } from './AccountWidgetWeeksSelect'

export function AccountTopPagesWidget(props: AccountTopPagesLogicProps): JSX.Element {
    const logic = accountTopPagesLogic(props)
    const { result, resultLoading, loadFailed, weeks, productKey } = useValues(logic)
    const { setWeeks, setProductKey, loadResult } = useActions(logic)

    return (
        <div className="flex flex-col gap-2">
            <AccountWidgetWeeksSelect weeks={weeks} onChange={setWeeks} />
            {loadFailed ? (
                <LemonBanner type="warning" action={{ children: 'Try again', onClick: () => loadResult() }}>
                    {result
                        ? "Couldn't refresh top pages. These pages are from the last range that loaded."
                        : "Couldn't load top pages for this account."}
                </LemonBanner>
            ) : null}
            {result ? (
                <AccountTopPages
                    result={result}
                    loading={resultLoading}
                    productKey={productKey}
                    onProductKeyChange={setProductKey}
                />
            ) : loadFailed ? null : (
                <LemonSkeleton className="h-64 w-full" />
            )}
        </div>
    )
}
