import { Link } from '@posthog/lemon-ui'

import type { AccountViewApi } from '../../generated/api.schemas'
import { AccountLogo } from '../Accounts/AccountLogo'
import { getAccountProductActivityUrl } from '../Accounts/accountProductActivityUrl'

export function ProductUsageAccountCell({
    accountId,
    name,
    products,
    truncated,
    views,
}: {
    accountId: string
    name: string
    products: number
    truncated: boolean
    views: AccountViewApi[]
}): JSX.Element {
    return (
        <div className="flex items-center gap-2 min-w-0">
            <AccountLogo name={name} />
            <div className="flex flex-col min-w-0">
                <Link className="font-semibold" to={getAccountProductActivityUrl(accountId, views)}>
                    {name}
                </Link>
                <span className="text-xs text-secondary">{`${truncated ? 'At least ' : ''}${products} ${products === 1 ? 'product' : 'products'} in range`}</span>
            </div>
        </div>
    )
}
