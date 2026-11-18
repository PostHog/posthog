import type { AICreditCardApi } from 'products/billing/frontend/generated/api.schemas'

// Stripe's brand names, shortened to fit the badge.
const BRAND_BADGES: Record<string, string> = {
    amex: 'AMEX',
    diners: 'DC',
    discover: 'DISC',
    mastercard: 'MC',
    unionpay: 'UP',
}

export function CardOnFile({ card }: { card: AICreditCardApi }): JSX.Element {
    return (
        <div className="flex h-10 items-center gap-2.5 rounded border px-3">
            <span className="flex h-5 w-8 shrink-0 items-center justify-center rounded-xs border bg-surface-secondary text-xxs font-extrabold tracking-wide">
                {BRAND_BADGES[card.brand] ?? card.brand.slice(0, 4).toUpperCase()}
            </span>
            <span className="flex-1 font-mono text-sm">···· {card.last4}</span>
            <span className="text-xs text-tertiary">
                Expires {String(card.exp_month).padStart(2, '0')}/{String(card.exp_year).slice(-2)}
            </span>
        </div>
    )
}
