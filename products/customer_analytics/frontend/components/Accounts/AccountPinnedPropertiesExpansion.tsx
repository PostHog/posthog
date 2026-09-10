import { AccountPinnedPropertiesPanel } from '../../scenes/CustomerAnalyticsAccountScene/components/AccountPinnedPropertiesPanel'

export function AccountPinnedPropertiesExpansion({ accountId }: { accountId: string }): JSX.Element {
    return (
        <div
            className="sticky left-0 w-[100cqw] max-w-full bg-bg-light"
            data-attr="account-pinned-properties-expansion"
        >
            <AccountPinnedPropertiesPanel accountId={accountId} layout="horizontal" source="list_expansion" />
        </div>
    )
}
