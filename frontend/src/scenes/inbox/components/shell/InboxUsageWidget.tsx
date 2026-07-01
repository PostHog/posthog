import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { BillingUpgradeCTA } from 'lib/components/BillingUpgradeCTA'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { currencyFormatter } from 'scenes/billing/billing-utils'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'
import { paymentEntryLogic } from 'scenes/billing/paymentEntryLogic'

import { BillingProductV2Type } from '~/types'

import { InboxUsageStatus, inboxUsageLogic } from '../../logics/inboxUsageLogic'

// Usage-bar fill colour by status. Main-app semantic Tailwind classes (not quill `--*` tokens —
// those only resolve inside `[data-quill]` subtrees).
const FILL_CLASS: Record<InboxUsageStatus, string> = {
    normal: 'bg-brand-blue',
    warning: 'bg-warning',
    limit: 'bg-danger',
}

const CARD_CLASS = 'flex flex-col gap-2 rounded border border-primary bg-surface-primary px-2.5 py-2'

/** A single status-coloured fill over a neutral track. Width is runtime-derived, hence inline. */
function UsageBar({ percentage, status }: { percentage: number; status: InboxUsageStatus }): JSX.Element {
    return (
        <div className="relative h-1 w-full overflow-hidden rounded-md bg-fill-tertiary">
            <div
                className={`absolute inset-y-0 left-0 ${FILL_CLASS[status]}`}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: `${percentage}%` }}
            />
        </div>
    )
}

function UsageCardSkeleton(): JSX.Element {
    return (
        <div className={CARD_CLASS}>
            <LemonSkeleton className="h-3 w-24" />
            <LemonSkeleton className="h-2 w-full" />
            <div className="flex items-center justify-between">
                <LemonSkeleton className="h-3 w-28" />
                <LemonSkeleton className="h-3 w-16" />
            </div>
        </div>
    )
}

/**
 * Runs the standard billing upgrade in place — same flow the billing page uses. The Stripe payment
 * modal is mounted globally (GlobalModals), so on click a returning customer is subscribed
 * immediately and a new one gets the card modal; either way billing reloads and this widget flips
 * to the editable subscribed state.
 */
function UpgradeButton({ product }: { product: BillingProductV2Type }): JSX.Element {
    const { billingProductLoading } = useValues(billingProductLogic({ product }))
    const { startPaymentEntryFlow } = useActions(paymentEntryLogic)

    return (
        <BillingUpgradeCTA
            type="primary"
            size="small"
            fullWidth
            center
            disableClientSideRouting
            loading={!!billingProductLoading}
            onClick={() => startPaymentEntryFlow(product, window.location.pathname + window.location.search)}
        >
            Upgrade to raise limit
        </BillingUpgradeCTA>
    )
}

function EditLimitModal(): JSX.Element {
    const { isModalOpen, freePrs, pricePerPrUsd, estimatedBudgetUsd, limitForm, isLimitFormSubmitting } =
        useValues(inboxUsageLogic)
    const { closeModal, submitLimitForm } = useActions(inboxUsageLogic)

    const billablePrs = Math.max(0, (limitForm.prs ?? 0) - freePrs)

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={closeModal}
            title="PR limit"
            description="How many pull requests agents can open each month before pausing."
            width={460}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={submitLimitForm} loading={isLimitFormSubmitting}>
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form logic={inboxUsageLogic} formKey="limitForm" className="flex flex-col gap-3">
                <LemonField name="prs" label="Monthly limit (PRs)">
                    <LemonInput type="number" min={0} step={1} autoFocus />
                </LemonField>
                <div className="flex flex-col gap-2 text-xs">
                    {freePrs > 0 && pricePerPrUsd != null && (
                        <span className="text-secondary">
                            The first {freePrs} PRs each month are free, then {currencyFormatter(pricePerPrUsd)} per PR.
                        </span>
                    )}
                    {estimatedBudgetUsd != null && pricePerPrUsd != null && (
                        <div className="flex flex-col gap-0.5 rounded bg-surface-secondary px-2 py-1.5">
                            <div className="flex items-center justify-between">
                                <span className="text-default">Estimated monthly budget</span>
                                <span className="font-semibold text-default tabular-nums">
                                    {currencyFormatter(estimatedBudgetUsd)}
                                </span>
                            </div>
                            <span className="text-tertiary">
                                {billablePrs > 0
                                    ? `${billablePrs} billable PRs × ${currencyFormatter(pricePerPrUsd)}`
                                    : 'Within the free tier'}
                            </span>
                        </div>
                    )}
                </div>
            </Form>
        </LemonModal>
    )
}

/**
 * Compact PR-usage meter for the inbox agents rail: a status-coloured usage bar with USD spent so far
 * alongside it, then `X / Y PRs created` on the left and `Resets <date>` on the right. On a paid plan
 * the limit is editable (and the edit affordance escalates to "Increase limit" at the cap); on the
 * free plan it shows an in-place upgrade instead. Renders nothing until billing has loaded and the
 * inbox product is present.
 */
export function InboxUsageWidget(): JSX.Element | null {
    const {
        product,
        isLoading,
        isSubscribed,
        canAccessBilling,
        usedPrsDisplay,
        limitPrs,
        freePrs,
        status,
        resetDate,
        spentUsd,
        percentage,
    } = useValues(inboxUsageLogic)
    const { openModal } = useActions(inboxUsageLogic)

    if (isLoading) {
        return <UsageCardSkeleton />
    }
    if (!product) {
        return null
    }

    // Only org admins/owners can change billing (canAccessBilling) — others get a read-only view with a hint.
    return (
        <>
            <div className={CARD_CLASS}>
                <div className="flex items-center justify-between gap-1.5">
                    <span className="text-[13px] font-semibold text-default">Pull requests</span>
                    {!isSubscribed ? (
                        <LemonTag type="muted" size="small">
                            Free plan
                        </LemonTag>
                    ) : canAccessBilling && status !== 'limit' ? (
                        <button
                            type="button"
                            onClick={openModal}
                            className="text-xs text-link hover:underline cursor-pointer bg-transparent border-0 p-0"
                        >
                            Edit
                        </button>
                    ) : null}
                </div>
                <div className="flex items-center gap-2">
                    <Tooltip title={freePrs > 0 ? `The first ${freePrs} PRs each month are free` : undefined}>
                        <div className="flex-1">
                            <UsageBar percentage={percentage} status={status} />
                        </div>
                    </Tooltip>
                    {spentUsd != null && (
                        <span className="text-xs font-medium text-default tabular-nums">
                            {currencyFormatter(spentUsd)}
                        </span>
                    )}
                </div>
                <div className="flex items-center justify-between gap-2 text-xs">
                    <span className="text-secondary tabular-nums">
                        <span className="font-medium text-default">{usedPrsDisplay}</span>
                        {limitPrs != null ? ` / ${limitPrs}` : ''} PRs created
                    </span>
                    {resetDate && (
                        <span className="text-tertiary tabular-nums">Resets {resetDate.format('MMM D')}</span>
                    )}
                </div>
                {canAccessBilling ? (
                    !isSubscribed ? (
                        <UpgradeButton product={product} />
                    ) : (
                        status === 'limit' && (
                            <LemonButton type="primary" size="small" fullWidth center onClick={openModal}>
                                Increase limit
                            </LemonButton>
                        )
                    )
                ) : (
                    (!isSubscribed || status === 'limit') && (
                        <span className="text-xs text-muted">
                            {isSubscribed
                                ? 'Contact an organization admin to raise the limit.'
                                : 'Contact an organization admin to upgrade.'}
                        </span>
                    )
                )}
            </div>
            {canAccessBilling && <EditLimitModal />}
        </>
    )
}
