import { useActions, useValues } from 'kea'

import { LemonButton, LemonCollapse, Link } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

import { MerchCodeLogicProps, PRESET_VALUES, merchCodeLogic } from './merchCodeLogic'

export function MerchCodePanel({ ticketId }: MerchCodeLogicProps): JSX.Element {
    const logic = merchCodeLogic({ ticketId })
    const { valueUsd, result, resultLoading } = useValues(logic)
    const { setValueUsd, generateCode } = useActions(logic)

    return (
        <LemonCollapse
            className="bg-surface-primary"
            panels={[
                {
                    key: 'merch-code',
                    header: 'Merch code',
                    content: (
                        <div className="flex flex-col gap-2">
                            <div>
                                <label className="text-xs text-muted-alt">Discount value (USD)</label>
                                <div className="flex flex-wrap gap-1 mt-1">
                                    {PRESET_VALUES.map((preset) => (
                                        <LemonButton
                                            key={preset}
                                            size="small"
                                            type={valueUsd === preset ? 'primary' : 'secondary'}
                                            onClick={() => setValueUsd(preset)}
                                        >
                                            ${preset}
                                        </LemonButton>
                                    ))}
                                </div>
                            </div>
                            <LemonButton
                                type="primary"
                                size="small"
                                fullWidth
                                center
                                loading={resultLoading}
                                disabledReason={
                                    valueUsd > 0
                                        ? result
                                            ? 'Code generated — change the amount to create another'
                                            : undefined
                                        : 'Choose a discount value first'
                                }
                                onClick={() => generateCode()}
                            >
                                Generate merch code
                            </LemonButton>
                            {result && (
                                <div className="flex flex-col gap-1 p-2 rounded bg-surface-secondary">
                                    <div className="flex items-center justify-between gap-2">
                                        <span className="text-xs text-muted-alt">Code</span>
                                        <CopyToClipboardInline
                                            description="merch code"
                                            className="font-mono font-semibold"
                                        >
                                            {result.code}
                                        </CopyToClipboardInline>
                                    </div>
                                    <div className="flex items-center justify-between gap-2">
                                        <span className="text-xs text-muted-alt">Value</span>
                                        <span className="text-xs font-semibold">${result.value_usd} off</span>
                                    </div>
                                    <div className="flex items-center justify-between gap-2">
                                        <span className="text-xs text-muted-alt">Store link</span>
                                        <CopyToClipboardInline
                                            description="store link"
                                            explicitValue={result.discount_url}
                                        >
                                            <Link
                                                to={result.discount_url}
                                                target="_blank"
                                                className="text-xs break-all"
                                            >
                                                {result.discount_url}
                                            </Link>
                                        </CopyToClipboardInline>
                                    </div>
                                    {result.admin_url && (
                                        <Link to={result.admin_url} target="_blank" className="text-xs">
                                            View in Shopify admin
                                        </Link>
                                    )}
                                </div>
                            )}
                        </div>
                    ),
                },
            ]}
        />
    )
}
