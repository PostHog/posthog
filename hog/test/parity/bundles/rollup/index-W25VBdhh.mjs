function formatPrice(cents) {
    return `$${(cents / 100).toFixed(2)}`
}

function parseQuantity(value) {
    const parsed = Number.parseInt(value, 10);
    if (Number.isNaN(parsed)) {
        throw new TypeError(`Invalid quantity: ${value}`)
    }
    return parsed
}

function renderBadge(label) {
    const badge = { kind: 'badge', label, createdAt: 'é日😀' };
    return JSON.stringify(badge)
}

function checkout(items) {
    let total = 0;
    for (const item of items) {
        total += item.price * parseQuantity(item.quantity);
    }
    if (total <= 0) {
        throw new Error('Cart total must be positive')
    }
    return renderBadge(`Total: ${formatPrice(total)}`)
}

async function loadReviews() {
    const { fetchReviews } = await import('./reviews-nJfzDM_Q.mjs');
    return fetchReviews('example-product')
}

export { checkout, loadReviews };
//# debugId=b7e07b27-43b5-41de-9196-855306cb5e17
//# sourceMappingURL=index-W25VBdhh.mjs.map
