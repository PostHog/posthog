import { useValues } from 'kea'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { csmHudSceneLogic } from '../logics/csmHudSceneLogic'
import { formatMoneyCompact } from '../utils/format'

function nrrTone(pct: number | null): 'success' | 'warning' | 'danger' | 'default' {
    if (pct == null) {
        return 'default'
    }
    if (pct >= 110) {
        return 'success'
    }
    if (pct >= 100) {
        return 'success'
    }
    if (pct >= 90) {
        return 'warning'
    }
    return 'danger'
}

export function NrrBadge(): JSX.Element | null {
    const { nrr, nrrLoading } = useValues(csmHudSceneLogic)
    if (nrrLoading && !nrr) {
        return <LemonTag type="default">NRR: …</LemonTag>
    }
    if (!nrr) {
        return null
    }
    const pct = nrr.nrrPct
    const tooltip = (
        <div className="text-xs">
            <div>
                Recent 6mo: {formatMoneyCompact(nrr.sumRecent6mo)} · Prior 6mo: {formatMoneyCompact(nrr.sumPrior6mo)}
            </div>
            <div>
                Counted: {nrr.accountsInCalc} of {nrr.accountsTotal}
                {nrr.accountsExcludedInactive > 0 && ` · inactive: ${nrr.accountsExcludedInactive}`}
                {nrr.accountsExcludedRefundOnly > 0 && ` · refund-only: ${nrr.accountsExcludedRefundOnly}`}
            </div>
        </div>
    )
    return (
        <Tooltip title={tooltip}>
            <LemonTag type={nrrTone(pct)}>NRR · {pct == null ? '—' : `${pct.toFixed(1)}%`}</LemonTag>
        </Tooltip>
    )
}
