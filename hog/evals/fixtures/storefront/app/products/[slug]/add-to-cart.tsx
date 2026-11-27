'use client'

import { useState } from 'react'

export function AddToCart({ slug }: { slug: string }) {
    const [added, setAdded] = useState(false)
    return (
        <button type="button" onClick={() => setAdded(true)} data-product={slug}>
            {added ? 'Added' : 'Add to cart'}
        </button>
    )
}
