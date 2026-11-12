export type ProductNumberKind = 'experiment' | 'evaluation'

const PIN_REASONS: Record<ProductNumberKind, string> = {
    experiment: "Experiments can't be pinned",
    evaluation: "Evaluations can't be pinned",
}

export function productNumberKind(key: string): ProductNumberKind | null {
    const prefix = key.split(':', 1)[0]
    return prefix === 'experiment' || prefix === 'evaluation' ? prefix : null
}

export function productNumberPinReason(key: string): string | null {
    const kind = productNumberKind(key)
    return kind ? PIN_REASONS[kind] : null
}
